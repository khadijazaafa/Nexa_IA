
import logging
import os

from dotenv import load_dotenv
from langchain.tools import tool
from langchain_tavily import TavilySearch

from tools.rag_tool import answer_question

load_dotenv()
logger = logging.getLogger(__name__)

# Initialisation de Tavily
tavily_tool = None

if os.getenv("TAVILY_API_KEY"):
    try:
        tavily_tool = TavilySearch(
            max_results=5,
            search_depth="advanced",
            include_answer=True,
        )
    except Exception:
        logger.exception("Impossible d'initialiser Tavily.")


def format_web_results(result) -> str:
    """Transforme la réponse Tavily en texte structuré."""

    if not isinstance(result, dict):
        return str(result)

    sections = []

    answer = result.get("answer")
    if answer:
        sections.append(f"Résumé de la recherche :\n{answer}")

    results = result.get("results", [])

    for index, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            continue

        title = item.get("title") or "Source sans titre"
        url = item.get("url") or ""
        content = item.get("content") or item.get("raw_content") or ""

        sections.append(
            f"Source {index}\n"
            f"Titre : {title}\n"
            f"URL : {url}\n"
            f"Contenu : {content}"
        )

    if not sections:
        return (
            "Aucun résultat exploitable n'a été retourné par la recherche Web."
        )

    return "\n\n".join(sections)


@tool
def safe_tavily(query: str) -> str:
    """Recherche sur le Web des informations actuelles et retourne les sources."""

    if tavily_tool is None:
        return (
            "La recherche Web est indisponible. "
            "Vérifiez la variable TAVILY_API_KEY dans le fichier .env."
        )

    try:
        result = tavily_tool.invoke({"query": query})
        formatted = format_web_results(result)

        logger.info("Recherche Tavily terminée pour : %s", query)
        return formatted

    except Exception:
        logger.exception("Échec de la recherche Tavily.")
        return (
            "La recherche Web a échoué. "
            "Vérifiez la clé Tavily, la connexion et les logs."
        )


@tool
def rag_qa(query: str) -> str:
    """Répond aux questions en utilisant la base documentaire PDF locale."""

    try:
        answer = answer_question(query)
        return str(answer)

    except Exception:
        logger.exception("Échec de la recherche documentaire RAG.")
        return (
            "Le service de questions-réponses sur les documents "
            "est momentanément indisponible."
        )


TOOLs = [safe_tavily, rag_qa]
