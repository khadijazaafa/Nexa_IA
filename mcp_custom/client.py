
import os

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_mcp_adapters.tools import load_mcp_tools

from async_graph import Agent

load_dotenv()


async def create_agent_from_session(
    session,
    db=None,
    username="user",
    role="user",
):
    """Create an agent using tools exposed by the MCP session."""

    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError(
            "GROQ_API_KEY is missing. Add it to your .env file."
        )

    model = ChatGroq(
        model=os.getenv(
            "GROQ_MODEL",
            "openai/gpt-oss-120b",
        ),
        temperature=0,
    )

    tools = await load_mcp_tools(session)

    # Only expose tools that do not require the unavailable CoinCap key.
    allowed_names = {"safe_tavily", "rag_qa"}

    if role == "admin":
        allowed_tools = [
            tool for tool in tools
            if tool.name in allowed_names
        ]
    else:
        allowed_tools = [
            tool for tool in tools
            if tool.name in allowed_names
        ]

    print(
        f"Tools loaded for {username} ({role}):",
        [tool.name for tool in allowed_tools],
    )

    agent = Agent(
        model=model,
        tools=allowed_tools,
        system=(
            "You are Agentic RAG Assistant. "
            "Answer clearly and accurately. "
            "Use rag_qa for questions about the indexed documents. "
            "Use safe_tavily when current web information is needed. "
            "Never claim you searched or read a document if the tool failed."
        ),
    )

    agent._mcp_session = session
    return agent
