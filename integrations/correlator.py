"""
Cross-incident correlation engine.

Groups related SAP alerts before sending to LLM — prevents duplicate RCA
and surfaces systemic issues (e.g. 5 RFC timeouts = network outage, not 5 separate incidents).

Correlation rules:
  1. Same error_code within 30 min window → group
  2. Same system_id + different error_codes within 10 min → systemic outage
  3. IDoc errors + Interface errors together → integration layer issue
"""
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)

# Time windows for correlation
SAME_ERROR_WINDOW_MIN   = 30
SYSTEMIC_WINDOW_MIN     = 10
INTEGRATION_CODES       = {"IDOC_ERROR", "INTERFACE_TIMEOUT", "IDOC_STATUS_FAILED", "CPI_ERROR"}


def correlate_incidents(incidents: list[dict]) -> list[dict]:
    """
    Input : flat list of SAP ALM incidents
    Output: list of correlated groups, each with a lead incident + related list

    Each group dict:
      {
        "lead": <incident>,           # primary incident for LLM analysis
        "related": [<incident>, ...], # correlated siblings
        "correlation_type": str,      # SAME_ERROR | SYSTEMIC_OUTAGE | INTEGRATION_LAYER
        "group_summary": str,         # human-readable group description
      }
    """
    if not incidents:
        return []

    used = set()
    groups = []

    for inc in incidents:
        if inc["id"] in used:
            continue

        related, corr_type = _find_related(inc, incidents, used)
        used.add(inc["id"])
        used.update(r["id"] for r in related)

        groups.append({
            "lead": inc,
            "related": related,
            "correlation_type": corr_type,
            "group_summary": _summarize(inc, related, corr_type),
        })

    logger.info("Correlated %d incidents into %d group(s)", len(incidents), len(groups))
    return groups


def _find_related(lead: dict, all_incidents: list[dict], used: set) -> tuple[list, str]:
    lead_time = _parse_time(lead.get("created_at", ""))
    lead_code = lead.get("error_code", "")
    lead_sys  = lead.get("system_id", "")

    same_error, systemic, integration = [], [], []

    for other in all_incidents:
        if other["id"] == lead["id"] or other["id"] in used:
            continue
        other_time = _parse_time(other.get("created_at", ""))
        diff_min = abs((lead_time - other_time).total_seconds()) / 60 if lead_time and other_time else 999

        if other.get("error_code") == lead_code and diff_min <= SAME_ERROR_WINDOW_MIN:
            same_error.append(other)
        elif other.get("system_id") == lead_sys and diff_min <= SYSTEMIC_WINDOW_MIN:
            systemic.append(other)
        elif lead_code in INTEGRATION_CODES and other.get("error_code") in INTEGRATION_CODES:
            integration.append(other)

    if same_error:
        return same_error, "SAME_ERROR"
    if systemic:
        return systemic, "SYSTEMIC_OUTAGE"
    if integration:
        return integration, "INTEGRATION_LAYER"
    return [], "STANDALONE"


def _summarize(lead: dict, related: list, corr_type: str) -> str:
    total = 1 + len(related)
    if corr_type == "SAME_ERROR":
        return f"{total}x {lead['error_code']} on {lead.get('system_id','SAP')} — likely same root cause"
    if corr_type == "SYSTEMIC_OUTAGE":
        codes = ", ".join({lead["error_code"]} | {r["error_code"] for r in related})
        return f"Systemic issue on {lead.get('system_id','SAP')}: {codes}"
    if corr_type == "INTEGRATION_LAYER":
        return f"Integration layer failure: {total} IDoc/Interface errors"
    return lead.get("title", lead["id"])


def _parse_time(ts: str):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
