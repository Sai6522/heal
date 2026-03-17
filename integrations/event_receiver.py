"""
Webhook receiver — SAP Cloud ALM pushes alerts here via HTTP POST.
Also supports SAP Event Mesh (AMQP/HTTP) message consumption.

Demo webhook secret: sap-healing-webhook-secret-demo
Replace in .env:
  WEBHOOK_SECRET=sap-healing-webhook-secret-demo
  EVENT_MESH_URL=https://enterprise-messaging-pubsub.cfapps.eu10.hana.ondemand.com
  EVENT_MESH_TOKEN_URL=https://your-subaccount.authentication.eu10.hana.ondemand.com/oauth/token
  EVENT_MESH_CLIENT_ID=sb-demo-client
  EVENT_MESH_CLIENT_SECRET=demo-secret-replace-me
  EVENT_MESH_QUEUE=sap/healing/alerts
"""
import os, hmac, hashlib, logging, httpx
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/events", tags=["events"])

WEBHOOK_SECRET    = os.getenv("WEBHOOK_SECRET", "sap-healing-webhook-secret-demo")
EVENT_MESH_URL    = os.getenv("EVENT_MESH_URL", "https://enterprise-messaging-pubsub.cfapps.eu10.hana.ondemand.com")
EVENT_MESH_TOKEN_URL   = os.getenv("EVENT_MESH_TOKEN_URL", "https://demo-subaccount.authentication.eu10.hana.ondemand.com/oauth/token")
EVENT_MESH_CLIENT_ID   = os.getenv("EVENT_MESH_CLIENT_ID", "sb-demo-client")
EVENT_MESH_CLIENT_SECRET = os.getenv("EVENT_MESH_CLIENT_SECRET", "demo-secret-replace-me")
EVENT_MESH_QUEUE  = os.getenv("EVENT_MESH_QUEUE", "sap/healing/alerts")


# ── Webhook endpoint (SAP Cloud ALM → POST here) ─────────────────────────────

@router.post("/webhook/alm-alert")
async def receive_alm_alert(request: Request, background_tasks: BackgroundTasks):
    """
    SAP Cloud ALM calls this endpoint when a new alert fires.
    Configure in SAP Cloud ALM → Operations → Alert Notification → Webhook.
    URL: https://your-btp-app.cfapps.eu10.hana.ondemand.com/events/webhook/alm-alert
    """
    # Verify HMAC signature sent by SAP Cloud ALM
    signature = request.headers.get("X-SAP-Signature", "")
    body = await request.body()
    if not _verify_signature(body, signature):
        logger.warning("Webhook signature mismatch — rejected")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()
    alert = _normalize_alm_alert(payload)
    logger.info("Webhook received: %s [%s]", alert["id"], alert["error_code"])

    # Trigger healing in background — return 200 immediately to SAP
    background_tasks.add_task(_heal_alert, alert)
    return {"status": "accepted", "incident_id": alert["id"]}


@router.post("/webhook/alm-alert/demo")
async def receive_alm_alert_demo(request: Request, background_tasks: BackgroundTasks):
    """Demo endpoint — no signature check. Use for local testing."""
    payload = await request.json()
    alert = _normalize_alm_alert(payload)
    logger.info("[DEMO] Webhook received: %s [%s]", alert["id"], alert["error_code"])
    background_tasks.add_task(_heal_alert, alert)
    return {"status": "accepted", "incident_id": alert["id"]}


# ── Event Mesh poller (pull-based fallback) ───────────────────────────────────

def poll_event_mesh() -> list[dict]:
    """
    Pull pending alerts from SAP Event Mesh queue.
    Call this from a scheduler or the /heal endpoint as fallback.
    """
    if "demo" in EVENT_MESH_CLIENT_ID:
        logger.info("[EVENT-MESH-DEMO] Returning mock events")
        return _mock_events()

    token = _get_event_mesh_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    alerts = []
    while True:
        r = httpx.post(
            f"{EVENT_MESH_URL}/messagingrest/v1/queues/{EVENT_MESH_QUEUE}/messages/consumption",
            headers=headers,
        )
        if r.status_code == 204:   # queue empty
            break
        r.raise_for_status()
        msg = r.json()
        alerts.append(_normalize_alm_alert(msg))
    return alerts


def _get_event_mesh_token() -> str:
    r = httpx.post(
        EVENT_MESH_TOKEN_URL,
        data={"grant_type": "client_credentials",
              "client_id": EVENT_MESH_CLIENT_ID,
              "client_secret": EVENT_MESH_CLIENT_SECRET},
    )
    r.raise_for_status()
    return r.json()["access_token"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _verify_signature(body: bytes, signature: str) -> bool:
    if not signature:
        return False
    expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("sha256="))


def _normalize_alm_alert(payload: dict) -> dict:
    """Map SAP Cloud ALM alert payload to internal incident format."""
    return {
        "id":         payload.get("alertId") or payload.get("id", "UNKNOWN"),
        "title":      payload.get("alertTitle") or payload.get("title", "SAP Alert"),
        "error_code": payload.get("errorCode") or payload.get("error_code", "UNKNOWN"),
        "priority":   payload.get("severity", payload.get("priority", "medium")).lower(),
        "system_id":  payload.get("systemId") or payload.get("system_id", "SAP-PRD"),
        "alert_type": payload.get("alertType", "UNKNOWN"),   # DUMP|JOB|RFC|IDOC|INTERFACE
        "created_at": payload.get("timestamp") or payload.get("created_at", ""),
    }


def _mock_events() -> list[dict]:
    return [
        {"id": "EVT-001", "title": "IDoc posting failed — MATMAS", "error_code": "IDOC_ERROR",
         "priority": "high", "system_id": "SAP-PRD", "alert_type": "IDOC", "created_at": "2026-03-17T10:00:00Z"},
        {"id": "EVT-002", "title": "CPI interface timeout — S4-to-SF", "error_code": "INTERFACE_TIMEOUT",
         "priority": "medium", "system_id": "SAP-PRD", "alert_type": "INTERFACE", "created_at": "2026-03-17T10:05:00Z"},
    ]


async def _heal_alert(alert: dict):
    """Background task: run full healing pipeline for a webhook-triggered alert."""
    from agents.orchestrator import run_healing_cycle_for_incident
    try:
        run_healing_cycle_for_incident(alert)
    except Exception as e:
        logger.error("Healing failed for %s: %s", alert["id"], e, exc_info=True)
