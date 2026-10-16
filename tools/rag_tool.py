
import os
import logging
from pathlib import Path
from threading import RLock

from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

load_dotenv()
logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

PDF_PATH = BASE_DIR / "data" / "attention.pdf"
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
FAISS_DIR = BASE_DIR / "data" / "faiss_index"

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-120b",
)
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

vectorstore = None
embeddings = None
rag_error = None
index_lock = RLock()


# ============================================================
# EMBEDDINGS
# ============================================================

def get_embeddings():
    """Initialise le modèle d'embeddings une seule fois."""
    global embeddings

    if embeddings is None:
        embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL
        )

    return embeddings


# ============================================================
# PDF PROCESSING
# ============================================================

def load_pdf_chunks(pdf_path: Path):
    """Charge un PDF et le découpe en segments."""
    documents = PyPDFLoader(str(pdf_path)).load()

    documents = [
        doc for doc in documents
        if doc.page_content and doc.page_content.strip()
    ]

    if not documents:
        raise ValueError(
            "Aucun texte extractible. Le PDF est peut-être "
            "scanné et nécessite une solution OCR."
        )

    for doc in documents:
        doc.metadata["source"] = pdf_path.name

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
    )

    chunks = splitter.split_documents(documents)

    if not chunks:
        raise ValueError(
            "Aucun segment de texte n'a été créé."
        )

    return chunks


# ============================================================
# FAISS PERSISTENCE
# ============================================================

def save_vectorstore():
    """Sauvegarde l'index FAISS sur le disque."""
    if vectorstore is None:
        raise RuntimeError(
            "Impossible de sauvegarder un index vide."
        )

    FAISS_DIR.mkdir(parents=True, exist_ok=True)

    vectorstore.save_local(str(FAISS_DIR))

    logger.info(
        "Index FAISS sauvegardé dans %s",
        FAISS_DIR,
    )


def load_saved_vectorstore():
    """
    Recharge l'index créé par l'application.

    Attention : index.pkl utilise la désérialisation pickle.
    Ne chargez jamais un index provenant d'une source non fiable.
    """
    index_file = FAISS_DIR / "index.faiss"
    metadata_file = FAISS_DIR / "index.pkl"

    if not index_file.is_file() or not metadata_file.is_file():
        return None

    return FAISS.load_local(
        str(FAISS_DIR),
        get_embeddings(),
        allow_dangerous_deserialization=True,
    )


# ============================================================
# INDEX A PDF
# ============================================================

def index_pdf(pdf_path: str | Path) -> int:
    """Indexe un PDF, l'ajoute à FAISS et sauvegarde l'index."""
    global vectorstore, rag_error

    path = Path(pdf_path).resolve()

    if path.suffix.lower() != ".pdf" or not path.is_file():
        raise ValueError(
            "Le fichier PDF est introuvable ou invalide."
        )

    with index_lock:
        chunks = load_pdf_chunks(path)
        embedder = get_embeddings()

        if vectorstore is None:
            vectorstore = FAISS.from_documents(
                chunks,
                embedder,
            )
        else:
            new_store = FAISS.from_documents(
                chunks,
                embedder,
            )
            vectorstore.merge_from(new_store)

        try:
            save_vectorstore()
        except Exception:
            logger.exception(
                "La sauvegarde de l'index FAISS a échoué."
            )
            # Signaler l'échec : le PDF ne doit pas être annoncé
            # comme durablement indexé si la sauvegarde a échoué.
            raise

        rag_error = None

        logger.info(
            "PDF indexé : %s (%s chunks)",
            path.name,
            len(chunks),
        )

        return len(chunks)


# ============================================================
# INITIALISATION AU DEMARRAGE
# ============================================================

def initialize_rag():
    """
    Recharge l'index sauvegardé.
    Si aucun index n'existe, indexe les PDF locaux puis
    sauvegarde le nouvel index.
    """
    global vectorstore, rag_error

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    FAISS_DIR.mkdir(parents=True, exist_ok=True)

    if not GROQ_API_KEY:
        rag_error = (
            "GROQ_API_KEY est absente du fichier .env."
        )
        logger.warning(rag_error)
        return

    with index_lock:
        try:
            saved_store = load_saved_vectorstore()

            if saved_store is not None:
                vectorstore = saved_store
                rag_error = None

                logger.info(
                    "Index FAISS persistant chargé depuis %s",
                    FAISS_DIR,
                )
                return

            pdf_paths = []

            if PDF_PATH.is_file():
                pdf_paths.append(PDF_PATH)

            pdf_paths.extend(
                sorted(UPLOAD_DIR.glob("*.pdf"))
            )

            if not pdf_paths:
                vectorstore = None
                rag_error = (
                    "Aucun PDF disponible. Téléversez un document "
                    "pour activer la recherche documentaire."
                )
                logger.warning(rag_error)
                return

            all_chunks = []

            for path in pdf_paths:
                try:
                    all_chunks.extend(
                        load_pdf_chunks(path)
                    )
                except Exception:
                    logger.exception(
                        "Impossible de charger le PDF %s",
                        path.name,
                    )

            if not all_chunks:
                raise ValueError(
                    "Aucun texte exploitable n'a été trouvé "
                    "dans les PDF."
                )

            vectorstore = FAISS.from_documents(
                all_chunks,
                get_embeddings(),
            )

            save_vectorstore()
            rag_error = None

            logger.info(
                "RAG initialisé : %s PDF, %s chunks",
                len(pdf_paths),
                len(all_chunks),
            )

        except Exception as exc:
            vectorstore = None
            rag_error = str(exc)

            logger.exception(
                "Échec de l'initialisation du RAG"
            )


# ============================================================
# QUESTIONS / REPONSES
# ============================================================

def answer_question(query: str) -> str:
    """Répond à une question à partir des documents indexés."""
    if vectorstore is None:
        return (
            "La recherche documentaire n'est pas disponible. "
            f"Détails : {rag_error or 'Index non initialisé.'}"
        )

    try:
        with index_lock:
            docs = vectorstore.as_retriever(
                search_kwargs={"k": 4}
            ).invoke(query)

        if not docs:
            return (
                "Aucun passage pertinent n'a été trouvé."
            )

        context = "\n\n".join(
            f"Source : {doc.metadata.get('source', 'inconnue')}\n"
            f"Page : {doc.metadata.get('page', 'inconnue')}\n"
            f"{doc.page_content}"
            for doc in docs
        )

        llm = ChatGroq(
            model=GROQ_MODEL,
            temperature=0,
        )

        response = llm.invoke([
            SystemMessage(
                content=(
                    "Tu es un assistant de recherche documentaire. "
                    "Réponds en français en te basant uniquement "
                    "sur le contexte fourni. Si l'information est "
                    "absente, dis clairement qu'elle n'est pas "
                    "mentionnée. N'invente aucun fait. Indique "
                    "le nom du PDF et la page lorsque ces "
                    "informations sont disponibles."
                )
            ),
            HumanMessage(
                content=(
                    f"Question :\n{query}\n\n"
                    f"Contexte des documents :\n{context}"
                )
            ),
        ])

        return str(response.content)

    except Exception:
        logger.exception(
            "Échec de la réponse RAG"
        )
        return (
            "Impossible de répondre à partir des documents. "
            "Consultez les logs du backend."
        )


# ============================================================
# INITIALISATION AUTOMATIQUE
# ============================================================

initialize_rag()
