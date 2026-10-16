
import os
import uuid
import logging
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator

from dotenv import load_dotenv
from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    File,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from auth import (
    Token,
    User,
    UserDB,
    UserCreate,
    get_db,
    authenticate_user,
    create_access_token,
    create_user,
    create_admin_user,
    get_current_active_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    require_role,
)

from database import (
    Base,
    ConversationDB,
    MessageDB,
    DocumentDB,
)

from auth import engine


# ============================================================
# 1. CONFIGURATION
# ============================================================

load_dotenv()

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(
            "logs/api.log",
            encoding="utf-8",
        ),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger("nexa_api")

abot = None
memory = None


# ============================================================
# 2. MODELES API
# ============================================================

class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=10000)
    session_id: Optional[str] = None


# ============================================================
# 3. UTILITAIRES UTILISATEUR ET CONVERSATION
# ============================================================

def get_user_db_id(
    db: Session,
    current_user: User,
) -> int:
    user = (
        db.query(UserDB)
        .filter(
            UserDB.username == current_user.username
        )
        .first()
    )

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Utilisateur introuvable.",
        )

    return user.id


def get_owned_conversation(
    db: Session,
    conversation_id: int,
    user_id: int,
) -> ConversationDB:
    conversation = (
        db.query(ConversationDB)
        .filter(
            ConversationDB.id == conversation_id,
            ConversationDB.user_id == user_id,
        )
        .first()
    )

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation introuvable.",
        )

    return conversation


def get_or_create_conversation(
    db: Session,
    user_id: int,
    session_id: Optional[str],
    query: str,
) -> ConversationDB:
    """
    Utilise l'identifiant numérique d'une conversation existante.
    Si aucun identifiant valide n'est fourni, crée une conversation.
    """

    if session_id:
        candidate = session_id.strip()

        if candidate.isdigit():
            conversation = get_owned_conversation(
                db,
                int(candidate),
                user_id,
            )
            return conversation

    conversation = ConversationDB(
        user_id=user_id,
        title=query.strip()[:255] or "Nouvelle conversation",
    )

    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return conversation


def save_message(
    db: Session,
    conversation: ConversationDB,
    role: str,
    content: str,
):
    message = MessageDB(
        conversation_id=conversation.id,
        role=role,
        content=content,
    )

    conversation.updated_at = datetime.utcnow()

    db.add(message)
    db.commit()
    db.refresh(message)

    return message


def extract_response(result) -> str:
    messages = result.get("messages", [])

    if not messages:
        return "Aucune réponse n'a été générée."

    content = getattr(messages[-1], "content", "")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []

        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))

        return "\n".join(parts) or "Réponse reçue sans texte."

    return str(content) if content else "Réponse reçue sans texte."


def make_graph_config(session_id: str) -> dict:
    return {
        "configurable": {
            "thread_id": session_id,
        }
    }


def get_agent_graph():
    if abot is None or abot.graph is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="L'agent IA n'est pas encore initialisé.",
        )

    return abot.graph


# ============================================================
# 4. INITIALISATION ADMINISTRATEUR
# ============================================================

def initialize_admin():
    username = os.getenv("ADMIN_USERNAME")
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")

    if not all([username, email, password]):
        logger.info(
            "Variables ADMIN_USERNAME, ADMIN_EMAIL ou "
            "ADMIN_PASSWORD absentes. Création admin ignorée."
        )
        return

    db_generator = get_db()
    db = next(db_generator)

    try:
        create_admin_user(
            db=db,
            username=username,
            email=email,
            password=password,
        )
        logger.info("Administrateur initialisé.")

    except Exception:
        logger.exception(
            "Impossible d'initialiser l'administrateur."
        )
        raise

    finally:
        db_generator.close()


# ============================================================
# 5. LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global abot, memory

    load_dotenv(override=False)

    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError(
            "GROQ_API_KEY est absente du fichier .env."
        )

    # Crée les tables manquantes sans supprimer les données existantes.
    # database.py doit importer Base depuis auth.py.
    Base.metadata.create_all(bind=engine)

    try:
        from graph import abot as configured_agent

        abot = configured_agent
        memory = MemorySaver()

        # Conservé provisoirement pour respecter la structure
        # personnalisée de ton agent actuel.
        abot.compile(memory)

        if abot.graph is None:
            raise RuntimeError(
                "Le graphe LangGraph n'a pas été compilé."
            )

        initialize_admin()

        logger.info("Nexa IA est démarré.")

    except Exception:
        logger.exception(
            "Erreur pendant le démarrage de Nexa IA."
        )
        raise

    yield

    logger.info("Arrêt de Nexa IA.")

    abot = None
    memory = None


# ============================================================
# 6. APPLICATION FASTAPI
# ============================================================

app = FastAPI(
    title="Nexa IA API",
    description=(
        "Assistant IA avec LangGraph, RAG, recherche Web "
        "et historique des conversations."
    ),
    version="1.1.0",
    lifespan=lifespan,
)


# ============================================================
# 7. CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# 8. ROUTES PUBLIQUES
# ============================================================

@app.get("/")
async def root():
    return {
        "name": "Nexa IA API",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    ready = abot is not None and abot.graph is not None

    return {
        "status": "healthy" if ready else "initializing",
        "agent_ready": ready,
    }


# ============================================================
# 9. INSCRIPTION
# ============================================================

@app.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
)
def signup(
    user: UserCreate,
    db: Session = Depends(get_db),
):
    try:
        create_user(db, user)

        return {
            "message": "Compte créé avec succès."
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("Erreur pendant l'inscription.")

        raise HTTPException(
            status_code=500,
            detail="Impossible de créer le compte.",
        )


# ============================================================
# 10. CONNEXION
# ============================================================

@app.post("/token", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = authenticate_user(
        db,
        form_data.username,
        form_data.password,
    )

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Nom d'utilisateur ou mot de passe incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={
            "sub": user.username,
            "role": user.role,
        },
        expires_delta=ACCESS_TOKEN_EXPIRE_MINUTES,
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


# ============================================================
# 11. CHAT CLASSIQUE AVEC HISTORIQUE SQLITE
# ============================================================

@app.post("/chat")
async def chat(
    req: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    graph = get_agent_graph()
    user_id = get_user_db_id(db, current_user)

    conversation = get_or_create_conversation(
        db=db,
        user_id=user_id,
        session_id=req.session_id,
        query=req.query,
    )

    session_id = str(conversation.id)

    try:
        save_message(
            db,
            conversation,
            "user",
            req.query,
        )

        result = await graph.ainvoke(
            {
                "messages": [
                    HumanMessage(content=req.query)
                ]
            },
            config=make_graph_config(session_id),
        )

        response_text = extract_response(result)

        save_message(
            db,
            conversation,
            "assistant",
            response_text,
        )

        return {
            "response": response_text,
            "session_id": session_id,
            "conversation_id": conversation.id,
        }

    except HTTPException:
        raise

    except Exception:
        db.rollback()

        logger.exception(
            "Erreur pendant le chat | session=%s",
            session_id,
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Une erreur est survenue pendant la génération "
                "de la réponse. Consultez logs/api.log."
            ),
        )


# ============================================================
# 12. CHAT STREAMING AVEC HISTORIQUE SQLITE
# ============================================================

@app.post("/chat/stream")
async def chat_stream(
    req: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    graph = get_agent_graph()
    user_id = get_user_db_id(db, current_user)

    conversation = get_or_create_conversation(
        db=db,
        user_id=user_id,
        session_id=req.session_id,
        query=req.query,
    )

    session_id = str(conversation.id)

    # Enregistre la question avant de commencer le streaming.
    save_message(
        db,
        conversation,
        "user",
        req.query,
    )

    async def generate() -> AsyncGenerator[str, None]:
        assistant_parts = []

        try:
            async for event in graph.astream_events(
                {
                    "messages": [
                        HumanMessage(content=req.query)
                    ]
                },
                config=make_graph_config(session_id),
                version="v2",
            ):
                if event.get("event") != "on_chat_model_stream":
                    continue

                chunk = event.get("data", {}).get("chunk")

                if chunk is None:
                    continue

                content = getattr(chunk, "content", "")

                if isinstance(content, str) and content:
                    assistant_parts.append(content)
                    yield content

                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            text_value = item.get("text", "")

                            if text_value:
                                assistant_parts.append(
                                    str(text_value)
                                )
                                yield str(text_value)

            final_response = "".join(assistant_parts)

            if final_response:
                save_message(
                    db,
                    conversation,
                    "assistant",
                    final_response,
                )

            logger.info(
                "Streaming terminé | session=%s",
                session_id,
            )

        except Exception:
            logger.exception(
                "Erreur pendant le streaming | session=%s",
                session_id,
            )

            db.rollback()

            yield (
                "\n\nUne erreur est survenue. "
                "Consultez les logs de l'API."
            )

    return StreamingResponse(
        generate(),
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Session-ID": session_id,
        },
    )


# ============================================================
# 13. LISTE DES CONVERSATIONS
# ============================================================

@app.get("/conversations")
def list_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    user_id = get_user_db_id(db, current_user)

    conversations = (
        db.query(ConversationDB)
        .filter(ConversationDB.user_id == user_id)
        .order_by(ConversationDB.updated_at.desc())
        .all()
    )

    return [
        {
            "id": item.id,
            "title": item.title,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }
        for item in conversations
    ]


# ============================================================
# 14. MESSAGES D'UNE CONVERSATION
# ============================================================

@app.get("/conversations/{conversation_id}/messages")
def list_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    user_id = get_user_db_id(db, current_user)

    conversation = get_owned_conversation(
        db,
        conversation_id,
        user_id,
    )

    return [
        {
            "id": item.id,
            "role": item.role,
            "content": item.content,
            "created_at": item.created_at.isoformat(),
        }
        for item in conversation.messages
    ]


# ============================================================
# 15. SUPPRESSION D'UNE CONVERSATION
# ============================================================

@app.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    user_id = get_user_db_id(db, current_user)

    conversation = get_owned_conversation(
        db,
        conversation_id,
        user_id,
    )

    db.delete(conversation)
    db.commit()

    return {
        "message": "Conversation supprimée."
    }


# ============================================================
# 16. UPLOAD PDF ET SAUVEGARDE EN BASE
# ============================================================

@app.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    from tools.rag_tool import UPLOAD_DIR, index_pdf

    original_name = Path(
        file.filename or "document.pdf"
    ).name

    if not original_name.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Seuls les fichiers PDF sont acceptés.",
        )

    content = await file.read(
        20 * 1024 * 1024 + 1
    )

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Le fichier est vide.",
        )

    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="La taille maximale autorisée est de 20 Mo.",
        )

    if not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=400,
            detail="Le fichier envoyé n'est pas un PDF valide.",
        )

    UPLOAD_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = UPLOAD_DIR / (
        f"{uuid.uuid4().hex}_{original_name}"
    )

    try:
        destination.write_bytes(content)

        chunks_count = await run_in_threadpool(
            index_pdf,
            destination,
        )

        user_id = get_user_db_id(
            db,
            current_user,
        )

        document = DocumentDB(
            user_id=user_id,
            filename=original_name,
            file_path=str(destination),
            status="indexed",
            chunks_indexed=chunks_count,
        )

        db.add(document)
        db.commit()
        db.refresh(document)

        logger.info(
            "PDF indexé | utilisateur=%s | fichier=%s | chunks=%s",
            current_user.username,
            original_name,
            chunks_count,
        )

        return {
            "message": "PDF téléversé et indexé avec succès.",
            "filename": original_name,
            "document_id": document.id,
            "chunks_indexed": chunks_count,
            "status": "indexed",
        }

    except HTTPException:
        raise

    except Exception:
        db.rollback()

        logger.exception(
            "Échec de l'upload ou de l'indexation du PDF."
        )

        if destination.exists():
            destination.unlink()

        raise HTTPException(
            status_code=500,
            detail=(
                "L'indexation du PDF a échoué. "
                "Consultez les logs du backend."
            ),
        )

    finally:
        await file.close()


# ============================================================
# 17. LISTE DES DOCUMENTS DE L'UTILISATEUR
# ============================================================

@app.get("/documents")
def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    user_id = get_user_db_id(
        db,
        current_user,
    )

    documents = (
        db.query(DocumentDB)
        .filter(DocumentDB.user_id == user_id)
        .order_by(DocumentDB.created_at.desc())
        .all()
    )

    return [
        {
            "id": item.id,
            "filename": item.filename,
            "status": item.status,
            "chunks_indexed": item.chunks_indexed,
            "created_at": item.created_at.isoformat(),
        }
        for item in documents
    ]


# ============================================================
# 18. ROUTE ADMINISTRATEUR
# ============================================================

@app.get("/admin-only")
async def admin_only(
    current_user: User = Depends(
        require_role("admin")
    ),
):
    return {
        "message": "Accès administrateur autorisé.",
        "username": current_user.username,
    }
