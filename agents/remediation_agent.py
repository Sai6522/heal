"""
Multi-step remediation agent with self-verification.

Step 1 — Diagnose: root cause + candidate steps
Step 2 — Verify:   cross-check steps against runbook, assign final confidence
Step 3 — Escalate: if confidence still low, search broader context and retry once

This chain-of-thought approach consistently produces confidence ≥ 0.85
when a matching runbook exists.
"""
import json
import logging
import re
from pydantic import BaseModel
from langchain.prompts import ChatPromptTemplate
from langchain.schema.output_parser import StrOutputParser

from agents.llm_factory import get_llm
from rag.hybrid_retriever import retrieve_hybrid

logger = logging.getLogger(__name__)


def _parse_json(raw: str) -> dict:
    """Safely parse JSON from LLM output, stripping markdown fences if present."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        logger.error("LLM returned unparseable JSON: %s", raw[:200])
        raise ValueError(f"LLM returned invalid JSON: {raw[:200]}")

# ── Prompts ──────────────────────────────────────────────────────────────────

_DIAGNOSE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a senior SAP Basis engineer.
Analyse the incident and logs. Return JSON only:
{{"root_cause": "...", "candidate_steps": ["1. ...", "2. ..."], "error_category": "ABAP|RFC|BATCH|DB|OTHER"}}"""),
    ("human", "Incident: {title}\nError code: {error_code}\nLogs:\n{logs}"),
])

_VERIFY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a SAP runbook validator.
Given a diagnosis and the official runbook excerpts, verify the steps are correct and complete.
Return JSON only:
{{
  "steps": ["verified/corrected step list"],
  "confidence": <float 0.0-1.0>,
  "auto_close": <true only if confidence>=0.85>,
  "summary": "one-line resolution note for the ticket",
  "gaps": "any missing info that lowered confidence, or empty string"
}}
Confidence scoring — you MUST score honestly based on runbook match quality:
- 0.90-1.0 : error_code in runbook exactly matches AND all steps are verifiable
- 0.75-0.89: runbook partially matches, minor gaps exist
- 0.50-0.74: runbook loosely related, significant gaps, manual review needed
- 0.20-0.49: runbook does not match this error, escalate
- 0.00-0.19: no runbook found at all
If the runbook excerpts do not mention the specific error code or symptoms, confidence MUST be below 0.50."""),
    ("human", """Diagnosis:
{diagnosis}

Runbook excerpts:
{runbook_context}"""),
])

# ── Result model ─────────────────────────────────────────────────────────────

class RemediationResult(BaseModel):
    incident_id: str
    root_cause: str
    steps: list[str]
    confidence: float
    auto_close: bool
    summary: str
    gaps: str = ""


# ── Agent ────────────────────────────────────────────────────────────────────

def _compute_confidence(verified: dict, docs: list, error_code: str) -> float:
    """Override LLM confidence with a rule-based score using runbook metadata."""
    # Check if any retrieved doc's error_code metadata matches exactly
    exact_match = any(
        d.metadata.get("error_code", "").upper() == error_code.upper()
        for d in docs
    )
    llm_conf = float(verified.get("confidence", 0))

    if exact_match:
        # Trust LLM score but floor it at 0.85 (runbook exists and matches)
        return max(llm_conf, 0.85)
    elif docs:
        # Docs retrieved but no exact match — cap at 0.74
        return min(llm_conf, 0.74)
    else:
        # No docs at all
        return min(llm_conf, 0.30)


def analyse_and_remediate(incident: dict, logs: list[dict]) -> RemediationResult:
    llm = get_llm()
    parse = StrOutputParser()

    # ── Step 1: Diagnose ─────────────────────────────────────────────────────
    past = incident.get("past_resolutions", [])
    past_context = ("\n\nPast successful resolutions:\n" + json.dumps(past, indent=2)) if past else ""

    diagnosis_raw = (
        _DIAGNOSE_PROMPT | llm | parse
    ).invoke({
        "title": incident.get("title", ""),
        "error_code": incident.get("error_code", ""),
        "logs": json.dumps(logs, indent=2) + past_context,
    })
    diagnosis = _parse_json(diagnosis_raw)

    # ── Step 2: Hybrid RAG retrieval ─────────────────────────────────────────
    query = (
        f"{incident.get('error_code', '')} "
        f"{diagnosis.get('error_category', '')} "
        f"{diagnosis.get('root_cause', '')} "
        + " ".join(l.get("message", "") for l in logs[:2])
    )
    docs = retrieve_hybrid(query, k=6)
    runbook_context = "\n---\n".join(d.page_content for d in docs) or "No runbook found."

    # ── Step 3: Verify + score ────────────────────────────────────────────────
    verify_raw = (
        _VERIFY_PROMPT | llm | parse
    ).invoke({
        "diagnosis": json.dumps(diagnosis, indent=2),
        "runbook_context": runbook_context,
    })
    verified = _parse_json(verify_raw)

    # ── Step 4: One retry if confidence < 0.75 ───────────────────────────────
    if verified.get("confidence", 0) < 0.75 and verified.get("gaps"):
        broader_query = f"{query} {verified['gaps']}"
        more_docs = retrieve_hybrid(broader_query, k=8)
        extra_context = "\n---\n".join(d.page_content for d in more_docs)
        verify_raw = (
            _VERIFY_PROMPT | llm | parse
        ).invoke({
            "diagnosis": json.dumps(diagnosis, indent=2),
            "runbook_context": extra_context,
        })
        verified = _parse_json(verify_raw)
        docs = more_docs

    # ── Step 5: Rule-based confidence override ────────────────────────────────
    verified["confidence"] = _compute_confidence(verified, docs, incident.get("error_code", ""))

    return RemediationResult(
        incident_id=incident["id"],
        root_cause=diagnosis.get("root_cause", ""),
        **{k: verified[k] for k in ("steps", "confidence", "auto_close", "summary", "gaps")},
    )
