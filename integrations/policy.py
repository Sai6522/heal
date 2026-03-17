"""
Policy engine & guardrails — decides whether auto-remediation is allowed.

Rules evaluated before any auto-close or runbook execution:
  1. Priority guardrail  : CRITICAL incidents always require human approval
  2. System guardrail    : Production systems (PRD) require higher confidence
  3. Change freeze       : Block auto-remediation during SAP change freeze windows
  4. Repeat failure      : If same fix failed 2+ times, escalate instead of retry
  5. Business hours      : Optionally restrict auto-close to business hours only
"""
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MIN_CONFIDENCE_PRD   = float(os.getenv("MIN_CONFIDENCE_PRD",   "0.90"))
MIN_CONFIDENCE_DEV   = float(os.getenv("MIN_CONFIDENCE_DEV",   "0.75"))
CHANGE_FREEZE_ACTIVE = os.getenv("CHANGE_FREEZE", "false").lower() == "true"
BUSINESS_HOURS_ONLY  = os.getenv("BUSINESS_HOURS_ONLY", "false").lower() == "true"
BUSINESS_HOURS_START = int(os.getenv("BUSINESS_HOURS_START", "8"))
BUSINESS_HOURS_END   = int(os.getenv("BUSINESS_HOURS_END",   "18"))
MANUAL_ONLY_CODES    = set(os.getenv("MANUAL_ONLY_CODES", "AUTH_FAILURE,SECURITY_ALERT").split(","))
PRD_SYSTEM_PATTERNS  = os.getenv("PRD_SYSTEMS", "PRD,P01,P1,PROD").split(",")


class PolicyDecision:
    def __init__(self, allowed: bool, reason: str, required_confidence: float = 0.85):
        self.allowed = allowed
        self.reason = reason
        self.required_confidence = required_confidence

    def __repr__(self):
        return f"PolicyDecision(allowed={self.allowed}, reason='{self.reason}')"


def evaluate(incident: dict, confidence: float, failed_attempts: int = 0) -> PolicyDecision:
    """
    Evaluate all guardrails. Returns PolicyDecision.
    Orchestrator must check .allowed before executing any remediation.
    """
    error_code = incident.get("error_code", "")
    priority   = incident.get("priority", "medium").lower()
    system_id  = incident.get("system_id", "")
    is_prd     = _is_production(system_id)

    if error_code in MANUAL_ONLY_CODES:
        return PolicyDecision(False, f"{error_code} is manual-only — human review required")

    if priority == "critical":
        return PolicyDecision(False, "CRITICAL priority — escalate to on-call, no auto-remediation")

    if CHANGE_FREEZE_ACTIVE:
        return PolicyDecision(False, "SAP change freeze active — all changes blocked")

    if failed_attempts >= 2:
        return PolicyDecision(False, f"Auto-fix failed {failed_attempts}x — escalating to SAP Basis team")

    if BUSINESS_HOURS_ONLY and not _in_business_hours():
        return PolicyDecision(False, "Outside business hours — queued for next business day")

    required = MIN_CONFIDENCE_PRD if is_prd else MIN_CONFIDENCE_DEV
    if confidence < required:
        return PolicyDecision(
            False,
            f"Confidence {confidence:.0%} below {'PRD' if is_prd else 'DEV'} threshold {required:.0%}",
            required_confidence=required,
        )

    return PolicyDecision(True, "All guardrails passed", required_confidence=required)


def _is_production(system_id: str) -> bool:
    sid = system_id.upper()
    return any(p.strip().upper() in sid for p in PRD_SYSTEM_PATTERNS)


def _in_business_hours() -> bool:
    hour = datetime.now(timezone.utc).hour
    return BUSINESS_HOURS_START <= hour < BUSINESS_HOURS_END
