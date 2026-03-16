# SAP Self-Healing & Auto-Remediation

Automated SAP incident analysis, remediation, and ticket closure using RAG + LLM.

```
┌─────────────────────────────────────────────────────────┐
│                    SAP ALM / Cloud ALM                  │
│              (open incidents + error logs)              │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │   Orchestrator       │  polls incidents
              └──────────┬───────────┘
                         │
              ┌──────────▼───────────┐
              │  Remediation Agent   │
              │  ┌────────────────┐  │
              │  │  RAG Retrieval │  │◄── ChromaDB (runbooks)
              │  └────────┬───────┘  │
              │           │          │
              │  ┌────────▼───────┐  │
              │  │  LLM Analysis  │  │◄── OpenAI GPT-4o / Ollama
              │  └────────┬───────┘  │
              └──────────┬───────────┘
                         │
              ┌──────────▼───────────┐
              │  confidence ≥ 0.85?  │
              │  YES → auto-close    │
              │  NO  → flag manual   │
              └──────────────────────┘
```

## Quick Start

```bash
cd sap-healing
cp .env.example .env          # fill in your keys
pip install -r requirements.txt

# 1. Index runbooks into vector store
python main.py index

# 2. Run one healing cycle (CLI)
python main.py heal

# 3. Or start the REST API
python main.py api
# → http://localhost:8000/docs
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/heal/sync` | Run healing cycle, return results |
| POST | `/heal` | Run healing cycle in background |
| GET | `/heal/results` | Last cycle results |
| POST | `/runbooks/reindex` | Re-ingest runbooks |
| POST | `/runbooks/search` | Search runbook RAG |

## LLM Options

Set `LLM_PROVIDER` in `.env`:

| Value | Model | Notes |
|-------|-------|-------|
| `openai` | GPT-4o | Requires `OPENAI_API_KEY` |
| `ollama` | llama3 / mistral | Run `ollama serve` locally |

For Ollama: `ollama pull llama3` then set `OLLAMA_MODEL=llama3`

## Adding Runbooks

Drop `.yaml` or `.md` files into `runbooks/`, then re-index:

```bash
python main.py index
# or via API:
curl -X POST http://localhost:8000/runbooks/reindex
```

Runbook YAML schema:
```yaml
error_code: YOUR_ERROR_CODE
title: Human readable title
symptoms: [...]
root_cause: "..."
remediation_steps: ["1. ...", "2. ..."]
auto_close_eligible: true
references: ["SAP Note XXXXXXX"]
```

## Auto-Close Threshold

Set `AUTO_CLOSE_CONFIDENCE=0.85` in `.env`.  
Tickets are only auto-closed when LLM confidence ≥ threshold AND `auto_close: true`.

## Project Structure

```
sap-healing/
├── main.py                  # CLI entry point
├── .env.example
├── requirements.txt
├── runbooks/                # SAP runbooks (YAML/MD) — add yours here
│   ├── SYSTEM_NO_ROLL.yaml
│   ├── RFC_TIMEOUT.yaml
│   └── JOB_FAILED.yaml
├── rag/
│   └── runbook_store.py     # ChromaDB ingestion + retrieval
├── agents/
│   ├── llm_factory.py       # OpenAI / Ollama switcher
│   ├── remediation_agent.py # Core LLM analysis agent
│   └── orchestrator.py      # Healing cycle loop
├── sap/
│   └── alm_client.py        # SAP ALM REST client (+ mock)
├── api/
│   └── main.py              # FastAPI server
└── data/
    ├── chroma/              # Vector DB (auto-created)
    └── logs/                # Local log storage
```
