"""Entry point — run healing cycle from CLI or start API server."""
import sys
from dotenv import load_dotenv
load_dotenv()

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "heal"

    if mode == "heal":
        from agents.orchestrator import run_healing_cycle
        run_healing_cycle()

    elif mode == "index":
        from rag.runbook_store import build_store
        build_store()
        print("Runbooks indexed.")

    elif mode == "api":
        import uvicorn
        uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)

    else:
        print("Usage: python main.py [heal|index|api]")
