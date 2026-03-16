"""
Demo runner — exercises the full pipeline with mock LLM responses.
No API keys needed. Shows RAG retrieval, agent reasoning, and ticket closure.
"""
import os, sys, json, time
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("CHROMA_DB_PATH", "./data/chroma")

from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax

console = Console()

# ── Mock LLM that returns canned responses ────────────────────────────────────

MOCK_RESPONSES = {
    "INC-001": {
        "diagnosis": {
            "root_cause": "Work process exhausted extended memory (em/initial_size_MB too low)",
            "candidate_steps": [
                "1. Check ST22 for dump details",
                "2. Review SM50 for high-memory work processes",
                "3. Increase em/initial_size_MB in DEFAULT.PFL",
                "4. Restart affected work process via SM50",
            ],
            "error_category": "ABAP",
        },
        "verification": {
            "steps": [
                "1. ST22 → confirm SYSTEM_NO_ROLL dump for program SAPMV45A",
                "2. SM50 → identify work process with high Private Memory",
                "3. SMEM → review extended memory distribution",
                "4. RZ10 → increase em/initial_size_MB to 4096 in DEFAULT.PFL",
                "5. SM50 → cancel affected work process (Process > Cancel with Core)",
                "6. Monitor ST22 — no new SYSTEM_NO_ROLL dumps after restart",
            ],
            "confidence": 0.93,
            "auto_close": True,
            "summary": "SYSTEM_NO_ROLL resolved: em/initial_size_MB increased to 4096, work process restarted",
            "gaps": "",
        },
    },
    "INC-002": {
        "diagnosis": {
            "root_cause": "RFC destination RFC_PROD unreachable due to network timeout",
            "candidate_steps": [
                "1. Test RFC connection in SM59",
                "2. Check network connectivity to target host",
                "3. Increase timeout in SM59 Technical Settings",
            ],
            "error_category": "RFC",
        },
        "verification": {
            "steps": [
                "1. SM59 → select RFC_PROD → Connection Test",
                "2. OS level: ping/telnet target host on port 3300",
                "3. SM59 → Technical Settings → increase Timeout to 120s",
                "4. Check target system load via SM50/SM66",
                "5. Verify firewall rules for port 33<NN>",
            ],
            "confidence": 0.88,
            "auto_close": True,
            "summary": "RFC_TIMEOUT resolved: SM59 timeout increased to 120s, network path verified",
            "gaps": "",
        },
    },
    "INC-003": {
        "diagnosis": {
            "root_cause": "Batch job RSUSR003 failed with return code 8 — missing authorization",
            "candidate_steps": [
                "1. Check SM37 job log for error details",
                "2. Run SU53 for background user",
                "3. Grant missing authorizations",
            ],
            "error_category": "BATCH",
        },
        "verification": {
            "steps": [
                "1. SM37 → find job RSUSR003 → Spool → read job log",
                "2. SU53 → check background user for missing auth objects",
                "3. SU01 → grant S_USER_GRP or relevant auth to background user",
                "4. SM12 → clear any stale object locks",
                "5. SM36 → reschedule job and monitor in SM37",
            ],
            "confidence": 0.79,
            "auto_close": False,
            "summary": "JOB_FAILED: authorization issue identified — manual auth grant required before re-run",
            "gaps": "Cannot auto-grant authorizations without security team approval",
        },
    },
}


def mock_llm_call(incident_id: str, step: str) -> dict:
    time.sleep(0.4)  # simulate LLM latency
    data = MOCK_RESPONSES.get(incident_id, MOCK_RESPONSES["INC-001"])
    return data["diagnosis"] if step == "diagnose" else data["verification"]


# ── Demo pipeline ─────────────────────────────────────────────────────────────

def run_demo():
    console.print(Panel.fit(
        "[bold cyan]SAP Self-Healing Demo[/bold cyan]\n"
        "[dim]RAG + LLM Agent Pipeline (mock mode — no API key needed)[/dim]",
        border_style="cyan",
    ))

    # Step 1: Index runbooks
    console.print("\n[bold]Step 1 — Indexing SAP runbooks into ChromaDB[/bold]")
    _index_runbooks()

    # Step 2: Fetch incidents
    console.print("\n[bold]Step 2 — Fetching open SAP ALM incidents[/bold]")
    from sap.alm_client import get_open_incidents, get_incident_logs
    incidents = get_open_incidents()
    for inc in incidents:
        console.print(f"  [yellow]•[/yellow] {inc['id']} [{inc['priority'].upper()}] {inc['title']}")

    # Step 3: Process each incident
    console.print("\n[bold]Step 3 — Running remediation agent[/bold]")
    results = []
    for inc in incidents:
        logs = get_incident_logs(inc["id"])
        result = _process_incident(inc, logs)
        results.append(result)

    # Step 4: Summary table
    _print_summary(results)

    # Step 5: Show resolution history
    _show_history()


def _index_runbooks():
    from rag.runbook_store import build_store
    try:
        store = build_store()
        console.print("  [green]✓[/green] Runbooks indexed into ChromaDB")
    except Exception as e:
        console.print(f"  [red]✗ Index error: {e}[/red]")
        sys.exit(1)


def _process_incident(inc: dict, logs: list[dict]) -> dict:
    iid = inc["id"]
    console.print(f"\n  [cyan]→ {iid}:[/cyan] {inc['title']}")

    # RAG retrieval
    from rag.hybrid_retriever import retrieve_hybrid
    query = f"{inc.get('error_code','')} {inc.get('title','')} {logs[0].get('message','') if logs else ''}"
    docs = retrieve_hybrid(query, k=4)
    console.print(f"    [dim]RAG: retrieved {len(docs)} runbook chunk(s)[/dim]")
    if docs:
        console.print(f"    [dim]Top match: {docs[0].metadata.get('source','?').split('/')[-1]}[/dim]")

    # Mock LLM: diagnose
    console.print(f"    [dim]LLM step 1/2: diagnosing...[/dim]")
    diagnosis = mock_llm_call(iid, "diagnose")
    console.print(f"    Root cause : {diagnosis['root_cause']}")
    console.print(f"    Category   : {diagnosis['error_category']}")

    # Mock LLM: verify
    console.print(f"    [dim]LLM step 2/2: verifying against runbook...[/dim]")
    verified = mock_llm_call(iid, "verify")
    conf = verified["confidence"]
    conf_color = "green" if conf >= 0.85 else "yellow" if conf >= 0.70 else "red"
    console.print(f"    Confidence : [{conf_color}]{conf:.0%}[/{conf_color}]")

    # Auto-close decision
    threshold = float(os.getenv("AUTO_CLOSE_CONFIDENCE", "0.85"))
    if verified["auto_close"] and conf >= threshold:
        from sap.alm_client import close_incident
        from sap.resolution_history import save_resolution
        close_incident(iid, verified["summary"])
        save_resolution(iid, inc.get("error_code",""), verified["steps"], verified["summary"])
        status = "[bold green]AUTO-CLOSED[/bold green]"
    elif conf < threshold:
        status = f"[yellow]MANUAL REVIEW[/yellow] (confidence {conf:.0%} < {threshold:.0%})"
    else:
        status = "[yellow]MANUAL REVIEW[/yellow] (security approval needed)"

    console.print(f"    Status     : {status}")
    if verified.get("gaps"):
        console.print(f"    Gaps       : [dim]{verified['gaps']}[/dim]")

    return {
        "incident_id": iid,
        "title": inc["title"],
        "confidence": conf,
        "auto_close": verified["auto_close"],
        "status": status,
        "steps": verified["steps"],
        "summary": verified["summary"],
    }


def _print_summary(results: list[dict]):
    console.print("\n[bold]Step 4 — Healing Cycle Summary[/bold]")
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Incident", style="cyan", width=10)
    table.add_column("Title", width=38)
    table.add_column("Confidence", justify="center", width=12)
    table.add_column("Outcome", width=22)

    for r in results:
        conf = r["confidence"]
        conf_str = f"{'🟢' if conf >= 0.85 else '🟡'} {conf:.0%}"
        table.add_row(r["incident_id"], r["title"][:38], conf_str, r["status"])

    console.print(table)

    auto_closed = sum(1 for r in results if r["confidence"] >= 0.85 and r["auto_close"])
    console.print(f"\n  Tickets auto-closed : [green]{auto_closed}/{len(results)}[/green]")
    console.print(f"  Avg confidence      : [cyan]{sum(r['confidence'] for r in results)/len(results):.0%}[/cyan]")


def _show_history():
    from sap.resolution_history import _load
    history = _load()
    if not history:
        return
    console.print("\n[bold]Step 5 — Resolution History (persisted for future confidence boost)[/bold]")
    for r in history:
        console.print(f"  [green]✓[/green] {r['incident_id']} [{r['error_code']}] — {r['summary'][:70]}")


if __name__ == "__main__":
    run_demo()
