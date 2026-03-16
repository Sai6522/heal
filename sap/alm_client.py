"""
SAP ALM Cloud client — fetches incidents/tickets and closes them.
Swap the HTTP calls for your actual SAP ALM REST endpoints.
"""
import os, httpx
from datetime import datetime

ALM_BASE = os.getenv("SAP_ALM_BASE_URL", "")
CLIENT_ID = os.getenv("SAP_ALM_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SAP_ALM_CLIENT_SECRET", "")
TOKEN_URL = os.getenv("SAP_ALM_TOKEN_URL", "")


def _get_token() -> str:
    if not TOKEN_URL:
        return "mock-token"
    r = httpx.post(TOKEN_URL, data={
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    })
    r.raise_for_status()
    return r.json()["access_token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}", "Content-Type": "application/json"}


def get_open_incidents() -> list[dict]:
    """Return open SAP ALM incidents. Falls back to mock data if no ALM URL set."""
    if not ALM_BASE:
        return _mock_incidents()
    r = httpx.get(f"{ALM_BASE}/api/v1/incidents?status=open", headers=_headers())
    r.raise_for_status()
    return r.json().get("value", [])


def get_incident_logs(incident_id: str) -> list[dict]:
    """Fetch dump/error logs attached to an incident."""
    if not ALM_BASE:
        return _mock_logs(incident_id)
    r = httpx.get(f"{ALM_BASE}/api/v1/incidents/{incident_id}/logs", headers=_headers())
    r.raise_for_status()
    return r.json().get("value", [])


def close_incident(incident_id: str, resolution_note: str) -> bool:
    """Close a ticket with a resolution note."""
    if not ALM_BASE:
        print(f"[MOCK] Closing ticket {incident_id}: {resolution_note[:80]}")
        return True
    r = httpx.patch(
        f"{ALM_BASE}/api/v1/incidents/{incident_id}",
        headers=_headers(),
        json={"status": "resolved", "resolutionNote": resolution_note,
              "resolvedAt": datetime.utcnow().isoformat()},
    )
    return r.status_code in (200, 204)


# ── Mock data for local dev ──────────────────────────────────────────────────

def _mock_incidents() -> list[dict]:
    return [
        {"id": "INC-001", "title": "ABAP dump SYSTEM_NO_ROLL", "priority": "high",
         "error_code": "SYSTEM_NO_ROLL", "created_at": "2026-03-15T04:00:00Z"},
        {"id": "INC-002", "title": "RFC connection timeout SM59", "priority": "medium",
         "error_code": "RFC_TIMEOUT", "created_at": "2026-03-15T05:30:00Z"},
        {"id": "INC-003", "title": "Batch job RSUSR003 failed", "priority": "low",
         "error_code": "JOB_FAILED", "created_at": "2026-03-15T06:00:00Z"},
    ]


def _mock_logs(incident_id: str) -> list[dict]:
    logs = {
        "INC-001": [{"timestamp": "2026-03-15T04:01:00Z",
                     "message": "SYSTEM_NO_ROLL: No roll area available. Work process terminated.",
                     "dump_type": "ABAP", "program": "SAPMV45A"}],
        "INC-002": [{"timestamp": "2026-03-15T05:31:00Z",
                     "message": "RFC destination RFC_PROD timed out after 60s. Check SM59.",
                     "dump_type": "RFC"}],
        "INC-003": [{"timestamp": "2026-03-15T06:01:00Z",
                     "message": "Job RSUSR003 step 1 ended with return code 8.",
                     "dump_type": "BATCH"}],
    }
    return logs.get(incident_id, [])
