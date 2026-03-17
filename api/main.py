"""
FastAPI REST API — healing cycles, webhook receiver, runbook management.
"""
import logging
import os
from fastapi import FastAPI, BackgroundTasks, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from agents.orchestrator import run_healing_cycle
from rag.runbook_store import build_store
from integrations.event_receiver import router as events_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("data/logs/api.log")],
)
logger = logging.getLogger(__name__)

app = FastAPI(title="SAP Self-Healing API", version="2.0")
app.include_router(events_router)   # /events/webhook/alm-alert

_bearer = HTTPBearer()
_API_TOKEN = os.getenv("API_SECRET_TOKEN", "demo-api-token-replace-me")
_last_results: list[dict] = []


def _verify_token(creds: HTTPAuthorizationCredentials = Security(_bearer)):
    if creds.credentials != _API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0"}


@app.post("/heal")
def trigger_healing(background_tasks: BackgroundTasks, _=Security(_verify_token)):
    def _run():
        global _last_results
        _last_results = run_healing_cycle()
    background_tasks.add_task(_run)
    return {"message": "Healing cycle started"}


@app.post("/heal/sync")
def trigger_healing_sync(_=Security(_verify_token)):
    global _last_results
    _last_results = run_healing_cycle()
    return {"results": _last_results}


@app.get("/heal/results")
def get_results(_=Security(_verify_token)):
    return {"results": _last_results}


@app.post("/runbooks/reindex")
def reindex_runbooks(_=Security(_verify_token)):
    try:
        build_store()
        return {"message": "Runbooks re-indexed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class RunbookQuery(BaseModel):
    query: str
    k: int = 5


@app.post("/runbooks/search")
def search_runbooks(body: RunbookQuery, _=Security(_verify_token)):
    from rag.runbook_store import retrieve
    docs = retrieve(body.query, k=body.k)
    return {"results": [{"content": d.page_content, "metadata": d.metadata} for d in docs]}
