"""
Resolution history store.

Every auto-closed ticket is saved here. On future incidents with the same
error code, past successful resolutions are injected into the LLM context,
which significantly boosts confidence scores.
"""
import json
from pathlib import Path
from datetime import datetime

HISTORY_FILE = Path(__file__).parent.parent / "data" / "resolution_history.json"


def save_resolution(incident_id: str, error_code: str, steps: list[str], summary: str):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    history = _load()
    history.append({
        "incident_id": incident_id,
        "error_code": error_code,
        "steps": steps,
        "summary": summary,
        "resolved_at": datetime.utcnow().isoformat(),
    })
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


def get_past_resolutions(error_code: str, limit: int = 3) -> list[dict]:
    """Return the most recent successful resolutions for this error code."""
    return [
        r for r in reversed(_load())
        if r.get("error_code") == error_code
    ][:limit]


def _load() -> list[dict]:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return []
