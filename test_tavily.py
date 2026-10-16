
from dotenv import load_dotenv

load_dotenv()

from tools.tools import safe_tavily

try:
    query = "What are the latest developments in artificial intelligence in 2026?"

    if hasattr(safe_tavily, "invoke"):
        result = safe_tavily.invoke({"query": query})
    else:
        result = safe_tavily(query)

    print("\n===== TAVILY TEST RESULT =====")
    print(result)
    print("\n===== TEST COMPLETED =====")

except Exception as e:
    print("\n===== TAVILY TEST FAILED =====")
    print(type(e).__name__)
    print(str(e))
