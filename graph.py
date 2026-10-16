
import os
import uuid
import asyncio
import logging
import platform

from dotenv import load_dotenv
from typing import TypedDict, Annotated
import operator

from langchain_core.messages import (
    AnyMessage,
    SystemMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END

from tools.tools import TOOLs


# ==================================================
# 1. Configuration
# ==================================================

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise ValueError(
        "GROQ_API_KEY is missing. Add it to your .env file."
    )

os.makedirs("logs", exist_ok=True)

logger = logging.getLogger("file_api_logger")
logger.setLevel(logging.INFO)

if not logger.handlers:
    file_handler = logging.FileHandler(
        "logs/app.log",
        encoding="utf-8"
    )

    formatter = logging.Formatter(
        "%(asctime)s, %(api_path)s, %(levelname)s, %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


# ==================================================
# 2. Groq model
# ==================================================

model = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0,
)


# ==================================================
# 3. Agent state
# ==================================================

class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]


# ==================================================
# 4. LangGraph Agent
# ==================================================

class Agent:

    def __init__(self, model, tools, system=""):
        self.system = system

        graph = StateGraph(AgentState)

        graph.add_node("llm", self.call_llm)
        graph.add_node("action", self.take_action)

        graph.add_conditional_edges(
            "llm",
            self.exists_action,
            {
                True: "action",
                False: END,
            }
        )

        graph.add_edge("action", "llm")
        graph.set_entry_point("llm")

        self._graph_base = graph

        self.tools = {
            getattr(tool, "__name__", getattr(tool, "name", str(tool))): tool
            for tool in tools
        }

        self.model = model.bind_tools(tools)
        self.graph = None

    def compile(self, memory):
        """Compile the graph with a persistent checkpointer."""
        self.graph = self._graph_base.compile(
            checkpointer=memory
        )

    def exists_action(self, state: AgentState):
        """Check whether the model requested a tool."""
        last_message = state["messages"][-1]
        return bool(getattr(last_message, "tool_calls", []))

    def call_llm(self, state: AgentState):
        """Invoke the chat model."""
        messages = state["messages"]

        if self.system:
            messages = [
                SystemMessage(content=self.system)
            ] + messages

        response = self.model.invoke(messages)

        return {"messages": [response]}

    def take_action(self, state: AgentState):
        """Execute requested tools and return their results."""
        tool_calls = state["messages"][-1].tool_calls
        results = []

        for tool_call in tool_calls:
            name = tool_call["name"]
            args = tool_call["args"]

            logger.info(
                "Executing tool: %s",
                name,
                extra={"api_path": "tool_execution"}
            )

            try:
                if name not in self.tools:
                    result = f"Unknown tool: {name}"
                else:
                    result = self.tools[name].invoke(args)

            except Exception:
                logger.exception(
                    "Tool execution failed: %s",
                    name,
                    extra={"api_path": "tool_execution"}
                )
                result = f"Tool {name} failed. Please try again."

            results.append(
                ToolMessage(
                    tool_call_id=tool_call["id"],
                    name=name,
                    content=str(result),
                )
            )

        return {"messages": results}


# ==================================================
# 5. Create agent
# ==================================================

abot = Agent(
    model=model,
    tools=TOOLs,
    system=(
        "You are a helpful AI assistant. "
        "Use the available tools when they are relevant. "
        "For questions about the provided PDF, use the RAG tool. "
        "For questions requiring current web information, use search. "
        "Do not invent tool results."
    ),
)


# ==================================================
# 6. Local terminal test
# ==================================================

async def chat_loop():
    """Interactive terminal test using in-memory conversation state."""
    from langgraph.checkpoint.memory import MemorySaver

    memory = MemorySaver()
    abot.compile(memory)

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    while True:
        query = input("Your question (or 'exit'): ").strip()

        if query.lower() == "exit":
            break

        if not query:
            continue

        messages = [HumanMessage(content=query)]

        async for event in abot.graph.astream_events(
            {"messages": messages},
            config,
            version="v2",
        ):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                content = chunk.content
                if isinstance(content, str):
                    print(content, end="", flush=True)

        print()


if platform.system() == "Windows":
    asyncio.set_event_loop_policy(
        asyncio.WindowsSelectorEventLoopPolicy()
    )


if __name__ == "__main__":
    asyncio.run(chat_loop())
