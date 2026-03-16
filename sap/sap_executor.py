"""
SAP action executor — runs the remediation steps INSIDE SAP.

Two modes:
  - RFC/BAPI  : direct SAP function calls via pyrfc (on-prem / RISE private)
  - OData REST: S/4HANA Cloud / BTP public APIs via httpx

Each action maps to a real SAP transaction/BAPI.
"""
import os
from dataclasses import dataclass

# pyrfc is optional — only available when SAP NW RFC SDK is installed
try:
    import pyrfc
    RFC_AVAILABLE = True
except ImportError:
    RFC_AVAILABLE = False

from sap.alm_client import _headers, ALM_BASE
import httpx

# ── SAP RFC connection config ─────────────────────────────────────────────────
RFC_PARAMS = {
    "ashost": os.getenv("SAP_HOST", ""),
    "sysnr":  os.getenv("SAP_SYSNR", "00"),
    "client": os.getenv("SAP_CLIENT", "100"),
    "user":   os.getenv("SAP_RFC_USER", ""),
    "passwd": os.getenv("SAP_RFC_PASS", ""),
}


@dataclass
class ActionResult:
    action: str
    success: bool
    message: str


# ── Public entry point ────────────────────────────────────────────────────────

def execute_remediation(error_code: str, steps: list[str], incident: dict) -> list[ActionResult]:
    """
    Map error_code → SAP actions → execute each one.
    Returns list of ActionResult so orchestrator knows what ran.
    """
    actions = _ACTION_MAP.get(error_code, [])
    if not actions:
        return [ActionResult("no-op", False, f"No automated actions defined for {error_code}")]

    results = []
    for action_fn in actions:
        result = action_fn(incident)
        results.append(result)
        if not result.success:
            break  # stop on first failure — don't cascade
    return results


# ── SAP Actions ───────────────────────────────────────────────────────────────

def _restart_work_process(incident: dict) -> ActionResult:
    """
    SM50 equivalent: cancel the stuck work process.
    BAPI: RFC_SYSTEM_INFO + TH_WPINFO + TH_CANCEL_WP
    """
    if not RFC_AVAILABLE or not RFC_PARAMS["ashost"]:
        return _mock("restart_work_process", "Work process cancelled via SM50 (mock)")

    try:
        with pyrfc.Connection(**RFC_PARAMS) as conn:
            # Get work process list
            wp_list = conn.call("TH_WPINFO")["WPLIST"]
            # Find work processes in PRIV (private memory) state
            stuck = [wp for wp in wp_list if wp.get("WP_STATUS") == "PRIV"]
            for wp in stuck:
                conn.call("TH_CANCEL_WP", WP_NO=wp["WP_NO"])
        return ActionResult("restart_work_process", True,
                            f"Cancelled {len(stuck)} stuck work process(es) via TH_CANCEL_WP")
    except Exception as e:
        return ActionResult("restart_work_process", False, str(e))


def _increase_memory_param(incident: dict) -> ActionResult:
    """
    RZ10 equivalent: update em/initial_size_MB in DEFAULT profile.
    BAPI: SYST_PARAMETER_SET (requires S_RZL_ADM authorization)
    """
    if not RFC_AVAILABLE or not RFC_PARAMS["ashost"]:
        return _mock("increase_memory", "em/initial_size_MB set to 4096 in DEFAULT.PFL (mock)")

    try:
        with pyrfc.Connection(**RFC_PARAMS) as conn:
            conn.call("SYST_PARAMETER_SET",
                      PARAMETER="em/initial_size_MB",
                      VALUE="4096",
                      PROFILE="DEFAULT")
        return ActionResult("increase_memory", True,
                            "em/initial_size_MB updated to 4096 in DEFAULT.PFL via SYST_PARAMETER_SET")
    except Exception as e:
        return ActionResult("increase_memory", False, str(e))


def _fix_rfc_timeout(incident: dict) -> ActionResult:
    """
    SM59 equivalent: update RFC destination timeout.
    OData API: /sap/opu/odata/sap/SXMB_MONI_BPE_SRV (or RFC DEST_MODIFY)
    """
    if not RFC_AVAILABLE or not RFC_PARAMS["ashost"]:
        return _mock("fix_rfc_timeout", "RFC destination timeout increased to 120s (mock)")

    try:
        with pyrfc.Connection(**RFC_PARAMS) as conn:
            conn.call("RFC_MODIFY_DESTINATION",
                      DESTINATION=os.getenv("SAP_RFC_DEST", "RFC_PROD"),
                      TIMEOUT="120")
        return ActionResult("fix_rfc_timeout", True,
                            "RFC destination timeout updated to 120s via RFC_MODIFY_DESTINATION")
    except Exception as e:
        return ActionResult("fix_rfc_timeout", False, str(e))


def _clear_object_locks(incident: dict) -> ActionResult:
    """
    SM12 equivalent: clear stale enqueue locks.
    BAPI: ENQUEUE_DELETE (clears locks for a specific user/object)
    """
    if not RFC_AVAILABLE or not RFC_PARAMS["ashost"]:
        return _mock("clear_locks", "Stale enqueue locks cleared via SM12 (mock)")

    try:
        with pyrfc.Connection(**RFC_PARAMS) as conn:
            conn.call("ENQUEUE_DELETE",
                      GUNAME=incident.get("background_user", ""),
                      GARG="*")
        return ActionResult("clear_locks", True, "Stale locks cleared via ENQUEUE_DELETE")
    except Exception as e:
        return ActionResult("clear_locks", False, str(e))


def _reschedule_job(incident: dict) -> ActionResult:
    """
    SM36 equivalent: reschedule the failed background job.
    BAPI: BP_JOB_SUBMIT
    """
    job_name = incident.get("job_name", "RSUSR003")
    if not RFC_AVAILABLE or not RFC_PARAMS["ashost"]:
        return _mock("reschedule_job", f"Job {job_name} rescheduled via BP_JOB_SUBMIT (mock)")

    try:
        with pyrfc.Connection(**RFC_PARAMS) as conn:
            result = conn.call("BP_JOB_SUBMIT",
                               JOBNAME=job_name,
                               JOBCOUNT=incident.get("job_count", ""),
                               STRTIMMED="X")  # start immediately
        return ActionResult("reschedule_job", True,
                            f"Job {job_name} rescheduled, new jobcount={result.get('JOBCOUNT','?')}")
    except Exception as e:
        return ActionResult("reschedule_job", False, str(e))


def _trigger_alm_automation(incident: dict, automation_id: str) -> ActionResult:
    """
    SAP Cloud ALM Automation: trigger a pre-defined runbook automation task.
    Used when RFC is not available (S/4HANA Cloud / BTP).
    REST: POST /api/v1/automations/{id}/trigger
    """
    if not ALM_BASE:
        return _mock("alm_automation", f"ALM automation {automation_id} triggered (mock)")

    try:
        r = httpx.post(
            f"{ALM_BASE}/api/v1/automations/{automation_id}/trigger",
            headers=_headers(),
            json={"incidentId": incident["id"], "parameters": {}},
        )
        r.raise_for_status()
        return ActionResult("alm_automation", True,
                            f"ALM automation {automation_id} triggered, executionId={r.json().get('executionId')}")
    except Exception as e:
        return ActionResult("alm_automation", False, str(e))


# ── Error code → action mapping ───────────────────────────────────────────────
# Add new error codes here as you expand the runbook library.

_ACTION_MAP: dict[str, list] = {
    "SYSTEM_NO_ROLL": [
        _restart_work_process,   # SM50: cancel stuck work process
        _increase_memory_param,  # RZ10: raise em/initial_size_MB
    ],
    "RFC_TIMEOUT": [
        _fix_rfc_timeout,        # SM59: increase destination timeout
    ],
    "JOB_FAILED": [
        _clear_object_locks,     # SM12: clear stale locks
        _reschedule_job,         # SM36: re-run the job
    ],
}


def _mock(action: str, message: str) -> ActionResult:
    print(f"  [SAP-MOCK] {action}: {message}")
    return ActionResult(action, True, message)
