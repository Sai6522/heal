"""
Self-healing orchestrator — full pipeline:

  SAP Cloud ALM / Webhook → Correlate → Policy check → LLM RCA
  → Runbook execution → ServiceNow update/close → Resolution history
"""
import os
import logging
from rich.console import Console
from rich.table import Table

from sap.alm_client import get_open_incidents, get_incident_logs, close_incident
from agents.remediation_agent import analyse_and_remediate
from sap.resolution_history import save_resolution, get_past_resolutions
from sap.alm_runbook_executor import execute_alm_runbook
from integrations.correlator import correlate_incidents
from integrations.policy import evaluate as policy_evaluate
from integrations.servicenow import create_snow_incident, update_snow_with_rca, close_snow_incident

console = Console()
logger = logging.getLogger(__name__)
AUTO_CLOSE_THRESHOLD = float(os.getenv("AUTO_CLOSE_CONFIDENCE", "0.85"))


def run_healing_cycle() -> list[dict]:
    """Poll SAP Cloud ALM and process all open incidents."""
    incidents = get_open_incidents()
    console.print(f"\n[bold cyan]Found {len(incidents)} open incident(s)[/bold cyan]")
    return _process_incident_list(incidents)


def run_healing_cycle_for_incident(incident: dict) -> dict:
    """Process a single incident — called from webhook handler."""
    results = _process_incident_list([incident])
    return results[0] if results else {}


def _process_incident_list(incidents: list[dict]) -> list[dict]:
    # Step 1: Correlate related alerts
    groups = correlate_incidents(incidents)
    console.print(f"[dim]Correlated into {len(groups)} group(s)[/dim]")

    results = []
    for group in groups:
        lead = group["lead"]
        if group["related"]:
            console.print(
                f"  [dim]Group [{group['correlation_type']}]: "
                f"{lead['id']} + {len(group['related'])} related — {group['group_summary']}[/dim]"
            )
        results.append(_process_one(lead, group))

    _print_summary(results)
    return results


def _process_one(inc: dict, group: dict) -> dict:
    console.print(f"\n[yellow]→ {inc['id']}: {inc['title']}[/yellow]")

    # Enrich incident with correlation context for LLM
    if group["related"]:
        inc["correlated_incidents"] = [
            {"id": r["id"], "error_code": r["error_code"], "title": r["title"]}
            for r in group["related"]
        ]
        inc["correlation_type"] = group["correlation_type"]

    # Inject past resolutions
    past = get_past_resolutions(inc.get("error_code", ""))
    if past:
        inc["past_resolutions"] = past

    logs = get_incident_logs(inc["id"])

    # Create ServiceNow incident immediately (track from start)
    snow_id = create_snow_incident(inc)
    console.print(f"  [dim]ServiceNow: {snow_id}[/dim]")

    # LLM analysis
    try:
        result = analyse_and_remediate(inc, logs)
    except Exception as e:
        logger.error("LLM error for %s: %s", inc["id"], e, exc_info=True)
        console.print(f"  [red]LLM error: {e}[/red]")
        update_snow_with_rca(snow_id, f"LLM analysis failed: {e}", [], 0.0)
        return {"incident_id": inc["id"], "snow_id": snow_id, "status": "error", "error": str(e)}

    # Post RCA to ServiceNow immediately (even if not auto-closing)
    update_snow_with_rca(snow_id, result.root_cause, result.steps, result.confidence)

    # Policy guardrail check
    policy = policy_evaluate(inc, result.confidence)
    console.print(f"  Policy     : {'✅ allowed' if policy.allowed else '🚫 blocked'} — {policy.reason}")

    status = "manual-review"
    if policy.allowed and result.auto_close and result.confidence >= AUTO_CLOSE_THRESHOLD:
        # Execute SAP Cloud ALM runbook
        run_result = execute_alm_runbook(inc.get("error_code", ""), inc)
        console.print(
            f"  ALM Runbook: [{'green' if run_result['success'] else 'red'}]"
            f"{run_result['status']}[/] — {run_result['output']}"
        )

        if run_result["success"]:
            # Close in SAP Cloud ALM
            closed = close_incident(result.incident_id, result.summary)
            # Close in ServiceNow with full RCA
            close_snow_incident(snow_id, result.summary, result.confidence)
            status = "auto-closed" if closed else "close-failed"
            if closed:
                save_resolution(result.incident_id, inc.get("error_code", ""),
                                result.steps, result.summary)
        else:
            status = f"runbook-failed:{run_result['status']}"
            close_snow_incident(snow_id, f"Runbook failed: {run_result['output']}", 0.0)
    else:
        reason = policy.reason if not policy.allowed else f"confidence={result.confidence:.0%}"
        status = f"manual-review ({reason})"
        close_snow_incident(snow_id, result.summary, result.confidence)

    console.print(f"  Root cause : {result.root_cause}")
    console.print(f"  Confidence : {result.confidence:.0%}")
    console.print(f"  Status     : [bold green]{status}[/bold green]")

    return {
        "incident_id": result.incident_id,
        "snow_id": snow_id,
        "status": status,
        "confidence": result.confidence,
        "root_cause": result.root_cause,
        "steps": result.steps,
        "summary": result.summary,
        "correlation_type": group.get("correlation_type", "STANDALONE"),
    }


def _print_summary(results: list[dict]):
    table = Table(title="Healing Cycle Summary")
    table.add_column("Incident", style="cyan")
    table.add_column("SNOW ID", style="dim")
    table.add_column("Correlation")
    table.add_column("Status", style="green")
    table.add_column("Confidence")
    for r in results:
        table.add_row(
            r["incident_id"],
            r.get("snow_id", "N/A"),
            r.get("correlation_type", "STANDALONE"),
            r.get("status", ""),
            f"{r.get('confidence', 0):.0%}" if "confidence" in r else "N/A",
        )
    console.print(table)
