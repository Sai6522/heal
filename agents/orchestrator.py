"""
Self-healing orchestrator.

Polls SAP ALM for open incidents → analyses each → auto-closes if confident.
"""
import os
import logging
from rich.console import Console
from rich.table import Table

from sap.alm_client import get_open_incidents, get_incident_logs, close_incident
from agents.remediation_agent import analyse_and_remediate
from sap.resolution_history import save_resolution, get_past_resolutions
from sap.alm_runbook_executor import execute_alm_runbook

console = Console()
logger = logging.getLogger(__name__)
AUTO_CLOSE_THRESHOLD = float(os.getenv("AUTO_CLOSE_CONFIDENCE", "0.85"))


def run_healing_cycle() -> list[dict]:
    incidents = get_open_incidents()
    console.print(f"\n[bold cyan]Found {len(incidents)} open incident(s)[/bold cyan]")

    results = []
    for inc in incidents:
        console.print(f"\n[yellow]→ Analysing {inc['id']}: {inc['title']}[/yellow]")
        logs = get_incident_logs(inc["id"])

        # Inject past successful resolutions → boosts LLM confidence
        past = get_past_resolutions(inc.get("error_code", ""))
        if past:
            inc["past_resolutions"] = past

        try:
            result = analyse_and_remediate(inc, logs)
        except Exception as e:
            logger.error("LLM error for %s: %s", inc["id"], e, exc_info=True)
            console.print(f"  [red]LLM error: {e}[/red]")
            results.append({"incident_id": inc["id"], "status": "error", "error": str(e)})
            continue

        status = "skipped"
        if result.auto_close and result.confidence >= AUTO_CLOSE_THRESHOLD:
            # 1. Trigger SAP Cloud ALM runbook — executes fix INSIDE SAP
            run_result = execute_alm_runbook(inc.get("error_code", ""), inc)
            console.print(f"  [{'green' if run_result['success'] else 'red'}]"
                          f"{'✓' if run_result['success'] else '✗'}[/] "
                          f"ALM Runbook [{run_result['status']}]: {run_result['output']}")

            # 2. Close ticket only if runbook succeeded
            if run_result["success"]:
                closed = close_incident(result.incident_id, result.summary)
                status = "auto-closed" if closed else "close-failed"
                if closed:
                    logger.info("Auto-closed %s (confidence=%.2f): %s",
                                result.incident_id, result.confidence, result.summary)
                    save_resolution(result.incident_id, inc.get("error_code", ""),
                                    result.steps, result.summary)
                else:
                    logger.warning("Failed to close ticket %s in ALM", result.incident_id)
            else:
                status = f"runbook-failed: {run_result['status']}"
        else:
            status = f"manual-review (confidence={result.confidence:.0%})"

        console.print(f"  Root cause : {result.root_cause}")
        console.print(f"  Confidence : {result.confidence:.0%}")
        console.print(f"  Status     : [bold green]{status}[/bold green]")

        results.append({
            "incident_id": result.incident_id,
            "status": status,
            "confidence": result.confidence,
            "root_cause": result.root_cause,
            "steps": result.steps,
            "summary": result.summary,
        })

    _print_summary(results)
    return results


def _print_summary(results: list[dict]):
    table = Table(title="Healing Cycle Summary")
    table.add_column("Incident", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Confidence")
    for r in results:
        table.add_row(
            r["incident_id"],
            r.get("status", ""),
            f"{r.get('confidence', 0):.0%}" if "confidence" in r else "N/A",
        )
    console.print(table)
