"""
SAP Cloud ALM Runbook Executor.

Instead of calling raw BAPIs, we trigger pre-defined SAP Cloud ALM
automation runbooks via REST API. SAP executes them inside the managed
SAP system on our behalf.

Flow:
  confidence >= 0.85
       │
       ▼
  lookup runbook_id for error_code   (ALM_RUNBOOK_MAP)
       │
       ▼
  POST /api/calm/automation/v1/runs  (trigger runbook in SAP Cloud ALM)
       │
       ▼
  poll GET  /api/calm/automation/v1/runs/{runId}  until COMPLETED/FAILED
       │
       ▼
  return result → orchestrator closes ticket if SUCCESS
"""
import os, time, httpx
from sap.alm_client import _headers, ALM_BASE

# Map your SAP Cloud ALM automation runbook IDs here.
# Find these in SAP Cloud ALM → Intelligent Event Processing → Automation.
ALM_RUNBOOK_MAP = {
    "SYSTEM_NO_ROLL":    os.getenv("ALM_RUNBOOK_SYSTEM_NO_ROLL",    "rb-system-no-roll-fix"),
    "RFC_TIMEOUT":       os.getenv("ALM_RUNBOOK_RFC_TIMEOUT",       "rb-rfc-timeout-fix"),
    "JOB_FAILED":        os.getenv("ALM_RUNBOOK_JOB_FAILED",        "rb-job-failed-fix"),
    "IDOC_ERROR":        os.getenv("ALM_RUNBOOK_IDOC_ERROR",        "rb-idoc-error-fix"),
    "INTERFACE_TIMEOUT": os.getenv("ALM_RUNBOOK_INTERFACE_TIMEOUT", "rb-interface-timeout-fix"),
}

POLL_INTERVAL = 5   # seconds between status checks
POLL_TIMEOUT  = 120 # max seconds to wait for runbook completion


def execute_alm_runbook(error_code: str, incident: dict) -> dict:
    """
    Trigger the SAP Cloud ALM automation runbook for this error code.
    Returns: {"success": bool, "status": str, "runId": str, "output": str}
    """
    runbook_id = ALM_RUNBOOK_MAP.get(error_code)
    if not runbook_id:
        return {"success": False, "status": "NO_RUNBOOK",
                "runId": "", "output": f"No ALM runbook mapped for {error_code}"}

    if not ALM_BASE:
        return _mock_execute(runbook_id, incident)

    # 1. Trigger the runbook
    run_id = _trigger(runbook_id, incident)

    # 2. Poll until done
    return _poll(run_id)


def _trigger(runbook_id: str, incident: dict) -> str:
    """POST to SAP Cloud ALM to start the runbook. Returns runId."""
    r = httpx.post(
        f"{ALM_BASE}/api/calm/automation/v1/runs",
        headers=_headers(),
        json={
            "runbookId": runbook_id,
            "context": {
                "incidentId":  incident["id"],
                "errorCode":   incident.get("error_code", ""),
                "systemId":    incident.get("system_id", ""),   # SAP SID e.g. "PRD"
                "priority":    incident.get("priority", "medium"),
            }
        },
    )
    r.raise_for_status()
    return r.json()["runId"]


def _poll(run_id: str) -> dict:
    """Poll SAP Cloud ALM until runbook finishes or times out."""
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        r = httpx.get(
            f"{ALM_BASE}/api/calm/automation/v1/runs/{run_id}",
            headers=_headers(),
        )
        r.raise_for_status()
        data = r.json()
        status = data.get("status")  # RUNNING | COMPLETED | FAILED | CANCELLED

        if status == "COMPLETED":
            return {"success": True,  "status": status, "runId": run_id,
                    "output": data.get("output", "Runbook completed successfully")}
        if status in ("FAILED", "CANCELLED"):
            return {"success": False, "status": status, "runId": run_id,
                    "output": data.get("errorMessage", "Runbook failed")}

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    return {"success": False, "status": "TIMEOUT", "runId": run_id,
            "output": f"Runbook did not complete within {POLL_TIMEOUT}s"}


def _mock_execute(runbook_id: str, incident: dict) -> dict:
    print(f"  [ALM-MOCK] Triggering runbook '{runbook_id}' for {incident['id']}")
    time.sleep(0.5)  # simulate execution time
    print(f"  [ALM-MOCK] Runbook '{runbook_id}' COMPLETED successfully")
    return {"success": True, "status": "COMPLETED", "runId": f"mock-run-{incident['id']}",
            "output": f"Runbook {runbook_id} executed all steps inside SAP successfully"}
