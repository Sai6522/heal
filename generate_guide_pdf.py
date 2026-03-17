"""Generate SAP Self-Healing — Real World Integration Guide PDF."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Preformatted
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

W, H = A4
OUT = "SAP_Self_Healing_Integration_Guide.pdf"

doc = SimpleDocTemplate(
    OUT, pagesize=A4,
    leftMargin=2*cm, rightMargin=2*cm,
    topMargin=2*cm, bottomMargin=2*cm,
)

base = getSampleStyleSheet()

# ── Custom styles ─────────────────────────────────────────────────────────────
def S(name, parent="Normal", **kw):
    return ParagraphStyle(name, parent=base[parent], **kw)

title_s   = S("T",  "Title",   fontSize=22, textColor=colors.HexColor("#1a3c5e"), spaceAfter=6)
sub_s     = S("Su", "Normal",  fontSize=11, textColor=colors.HexColor("#4a6fa5"), spaceAfter=14, alignment=TA_CENTER)
h1_s      = S("H1", "Heading1",fontSize=14, textColor=colors.HexColor("#1a3c5e"), spaceBefore=16, spaceAfter=6)
h2_s      = S("H2", "Heading2",fontSize=11, textColor=colors.HexColor("#2e6da4"), spaceBefore=10, spaceAfter=4)
body_s    = S("B",  "Normal",  fontSize=9,  leading=14, spaceAfter=4)
bullet_s  = S("BL", "Normal",  fontSize=9,  leading=14, leftIndent=14, spaceAfter=3,
               bulletIndent=4, bulletFontName="Helvetica")
code_s    = ParagraphStyle("C", fontName="Courier", fontSize=8, leading=12,
                            backColor=colors.HexColor("#f4f4f4"), leftIndent=10,
                            rightIndent=10, spaceBefore=4, spaceAfter=6,
                            borderPadding=(4,6,4,6))
note_s    = S("N",  "Normal",  fontSize=8,  textColor=colors.HexColor("#666666"),
               leftIndent=10, spaceAfter=4)

def h1(t): return Paragraph(t, h1_s)
def h2(t): return Paragraph(t, h2_s)
def p(t):  return Paragraph(t, body_s)
def bl(t): return Paragraph(f"• {t}", bullet_s)
def code(t): return Preformatted(t, code_s)
def note(t): return Paragraph(f"<i>{t}</i>", note_s)
def sp(n=6): return Spacer(1, n)
def hr(): return HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc"), spaceAfter=6)

def tbl(data, col_widths, header=True):
    t = Table(data, colWidths=col_widths)
    style = [
        ("FONTNAME",    (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE",    (0,0), (-1,-1), 8),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f7f9fc")]),
        ("GRID",        (0,0), (-1,-1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN",      (0,0), (-1,-1), "TOP"),
        ("TOPPADDING",  (0,0), (-1,-1), 4),
        ("BOTTOMPADDING",(0,0),(-1,-1), 4),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]
    if header:
        style += [
            ("BACKGROUND",  (0,0), (-1,0), colors.HexColor("#1a3c5e")),
            ("TEXTCOLOR",   (0,0), (-1,0), colors.white),
            ("FONTNAME",    (0,0), (-1,0), "Helvetica-Bold"),
        ]
    t.setStyle(TableStyle(style))
    return t

# ── Content ───────────────────────────────────────────────────────────────────
story = []

# Cover
story += [
    sp(40),
    Paragraph("SAP Self-Healing System", title_s),
    Paragraph("Real-World Integration Guide", sub_s),
    hr(),
    p("This guide covers how to deploy, configure, and extend the SAP Self-Healing project "
      "in a real SAP RISE / SAP Cloud ALM environment — from adding runbooks to connecting "
      "ServiceNow and SAP Event Mesh."),
    sp(4),
    tbl([
        ["Project", "github.com/Sai6522/heal"],
        ["Stack",   "Python 3.10 · FastAPI · LangChain · ChromaDB · Ollama / OpenAI"],
        ["Target",  "SAP RISE · SAP Cloud ALM · SAP BTP · ServiceNow"],
    ], [4*cm, 12*cm], header=False),
    sp(20),
]

# ── Section 1 ─────────────────────────────────────────────────────────────────
story += [
    h1("Step 1 — Add Real Runbooks"),
    hr(),
    p("Every SAP error you want to auto-heal needs a YAML runbook in the <b>runbooks/</b> folder. "
      "The LLM uses the runbook content to validate its diagnosis and assign a confidence score. "
      "Higher quality runbooks = higher confidence = more auto-closures."),
    sp(),
    h2("Runbook Template"),
    code(
"""# runbooks/YOUR_ERROR_CODE.yaml
error_code: YOUR_ERROR_CODE        # must match exactly what SAP ALM sends
title: Human readable title
category: ABAP|RFC|BATCH|DB|IDOC|INTERFACE

symptoms:
  - What you see in the system (transaction codes, error messages)

root_cause: >
  Explain WHY this happens. The LLM uses this to validate its diagnosis.
  More detail = higher confidence scores.

remediation_steps:
  - "1. Transaction -> what to do"
  - "2. Next step"
  - "3. Verification step"

auto_close_eligible: true    # false = always needs human (security issues etc.)

references:
  - "SAP Note 1234567\""""
    ),
    sp(),
    h2("Recommended Error Codes to Add"),
    tbl([
        ["Error Code", "SAP Area", "Key Transactions"],
        ["DBIF_RSQL_SQL_ERROR",       "DB lock / timeout",      "ST22, DB02"],
        ["TSV_TNEW_PAGE_ALLOC_FAILED","Memory overflow",         "ST22, SM50"],
        ["MESSAGE_TYPE_X",            "ABAP runtime error",      "ST22"],
        ["ENQUEUE_FAILED",            "Lock table overflow",     "SM12, SM21"],
        ["SPOOL_NO_INFO",             "Spool overflow",          "SP01, SP12"],
        ["IDOC_STATUS_FAILED",        "IDoc status 02/56",       "WE02, BD87"],
        ["SM59_RFC_ERROR",            "RFC config broken",       "SM59"],
        ["BATCH_JOB_ABORTED",         "Job aborted",             "SM37, SM36"],
    ], [5.5*cm, 5.5*cm, 5.5*cm]),
    sp(),
    p("After adding any YAML file, re-index ChromaDB:"),
    code("python main.py index"),
]

# ── Section 2 ─────────────────────────────────────────────────────────────────
story += [
    h1("Step 2 — Connect Real SAP Cloud ALM"),
    hr(),
    p("Get these values from <b>SAP BTP Cockpit → your subaccount → SAP Cloud ALM → Service Keys</b>."),
    code(
"""# .env
SAP_ALM_BASE_URL=https://YOUR-TENANT.alm.cloud.sap
SAP_ALM_CLIENT_ID=sb-your-actual-client-id
SAP_ALM_CLIENT_SECRET=your-actual-secret
SAP_ALM_TOKEN_URL=https://YOUR-TENANT.authentication.eu10.hana.ondemand.com/oauth/token"""
    ),
    h2("Navigation Path in BTP Cockpit"),
    bl("BTP Cockpit → Subaccount → Instances and Subscriptions"),
    bl("SAP Cloud ALM → Service Keys → Create Key"),
    bl("Copy: clientid, clientsecret, url"),
    sp(),
    h2("Test the Connection"),
    code('python -c "from sap.alm_client import get_open_incidents; print(get_open_incidents())"'),
]

# ── Section 3 ─────────────────────────────────────────────────────────────────
story += [
    h1("Step 3 — Set Up Webhook (Real-time Push)"),
    hr(),
    p("The webhook replaces polling — SAP Cloud ALM calls your app the moment an alert fires. "
      "This gives you near-instant response instead of waiting for the next poll cycle."),
    sp(),
    h2("1. Deploy to SAP BTP Cloud Foundry"),
    code(
"""# manifest.yml (create in project root)
applications:
  - name: sap-healing
    memory: 512M
    command: python main.py api
    buildpacks: [python_buildpack]

cf push sap-healing"""
    ),
    h2("2. Register Webhook in SAP Cloud ALM"),
    bl("SAP Cloud ALM → Operations → Alert Notification"),
    bl("Create Notification → Type: Webhook"),
    bl("URL: https://sap-healing.cfapps.eu10.hana.ondemand.com/events/webhook/alm-alert"),
    bl("Secret: same value as WEBHOOK_SECRET in your .env"),
    bl("Events: Alert Created, Alert Updated"),
    sp(),
    h2("3. Test with curl"),
    code(
"""curl -X POST https://your-app/events/webhook/alm-alert/demo \\
  -H "Content-Type: application/json" \\
  -d '{"alertId":"INC-TEST","alertTitle":"ABAP dump",
       "errorCode":"SYSTEM_NO_ROLL","severity":"high","systemId":"PRD"}'"""
    ),
]

# ── Section 4 ─────────────────────────────────────────────────────────────────
story += [
    h1("Step 4 — Connect Real ServiceNow"),
    hr(),
    p("The system creates a ServiceNow ticket the moment an alert arrives, posts the AI-generated "
      "RCA as a work note, then closes or assigns the ticket based on confidence."),
    sp(),
    h2("1. Get a Free Dev Instance"),
    p("Go to <b>developer.servicenow.com</b> → Request Instance (free, takes ~5 min)"),
    sp(),
    h2("2. Set Credentials in .env"),
    code(
"""SNOW_INSTANCE=dev12345.service-now.com
SNOW_USER=admin
SNOW_PASS=your-actual-password
SNOW_ASSIGNMENT_GROUP=SAP-BASIS-TEAM"""
    ),
    h2("3. Create Assignment Group in ServiceNow"),
    bl("ServiceNow → User Administration → Groups → New"),
    bl("Name: SAP-BASIS-TEAM (must match SNOW_ASSIGNMENT_GROUP exactly)"),
    bl("Add your SAP Basis team members"),
    sp(),
    h2("4. Test"),
    code(
"""python -c "
from integrations.servicenow import create_snow_incident
sid = create_snow_incident({'id':'TEST-001','title':'Test',
      'error_code':'TEST','priority':'low','system_id':'DEV'})
print('Created SNOW ticket:', sid)
\""""
    ),
    h2("ServiceNow Ticket Lifecycle"),
    tbl([
        ["Event", "ServiceNow Action"],
        ["Alert received",          "Incident created (state: New)"],
        ["LLM RCA complete",        "Work note added with root cause + steps + confidence %"],
        ["confidence >= threshold", "Incident resolved (Solved by AI)"],
        ["confidence < threshold",  "Incident assigned to SAP-BASIS-TEAM for manual review"],
    ], [6*cm, 10.5*cm]),
]

# ── Section 5 ─────────────────────────────────────────────────────────────────
story += [
    h1("Step 5 — Map SAP Cloud ALM Automation Runbooks"),
    hr(),
    p("For each error code, create a pre-built automation in SAP Cloud ALM. "
      "The system triggers these automations to execute the actual fix inside SAP."),
    sp(),
    h2("Create Automation in SAP Cloud ALM"),
    bl("SAP Cloud ALM → Intelligent Event Processing → Automation → Create"),
    bl("Name: rb-system-no-roll-fix"),
    bl("Add steps: restart work process, increase em/initial_size_MB"),
    bl("Save → copy the Automation ID"),
    sp(),
    h2("Map IDs in .env"),
    code(
"""ALM_RUNBOOK_SYSTEM_NO_ROLL=<actual-automation-id>
ALM_RUNBOOK_RFC_TIMEOUT=<actual-automation-id>
ALM_RUNBOOK_JOB_FAILED=<actual-automation-id>
ALM_RUNBOOK_IDOC_ERROR=<actual-automation-id>
ALM_RUNBOOK_INTERFACE_TIMEOUT=<actual-automation-id>"""
    ),
]

# ── Section 6 ─────────────────────────────────────────────────────────────────
story += [
    h1("Step 6 — Tune Policy Guardrails"),
    hr(),
    p("The policy engine decides whether auto-remediation is allowed before any action is taken. "
      "Tune these settings to match your company's change management rules."),
    code(
"""# .env
PRD_SYSTEMS=PRD,P01,P1           # your actual production SIDs
MIN_CONFIDENCE_PRD=0.90          # stricter threshold for production
MIN_CONFIDENCE_DEV=0.75          # threshold for dev/QA systems
MANUAL_ONLY_CODES=AUTH_FAILURE,SECURITY_ALERT   # never auto-close these
CHANGE_FREEZE=false              # set true during SAP upgrades/maintenance
BUSINESS_HOURS_ONLY=true         # only auto-close 8am-6pm
BUSINESS_HOURS_START=8
BUSINESS_HOURS_END=18"""
    ),
    sp(),
    tbl([
        ["Guardrail", "Behaviour"],
        ["CRITICAL priority",    "Always blocked — escalate to on-call"],
        ["PRD system",           "Requires MIN_CONFIDENCE_PRD (default 90%)"],
        ["CHANGE_FREEZE=true",   "All auto-remediation blocked"],
        ["Failed 2+ times",      "Escalates to SAP Basis team instead of retrying"],
        ["MANUAL_ONLY_CODES",    "Listed error codes always go to human review"],
        ["BUSINESS_HOURS_ONLY",  "Queues actions outside configured hours"],
    ], [5.5*cm, 11*cm]),
]

# ── Section 7 ─────────────────────────────────────────────────────────────────
story += [
    h1("Step 7 — Run in Production"),
    hr(),
    h2("Start the API Server (always-on, receives webhooks)"),
    code("python main.py api"),
    h2("Run One Healing Cycle Manually"),
    code("python main.py heal"),
    h2("Re-index After Adding New Runbooks"),
    code("python main.py index"),
    sp(),
    h2("Recommended Production Setup on SAP BTP"),
    tbl([
        ["Component", "Command", "Purpose"],
        ["API Server",    "python main.py api",   "Always-on, receives webhook alerts instantly"],
        ["Cron (15 min)", "python main.py heal",  "Catches anything webhooks missed (fallback poll)"],
        ["On-demand",     "python main.py index", "Run after adding/updating runbooks"],
    ], [4*cm, 5.5*cm, 7*cm]),
]

# ── Section 8 ─────────────────────────────────────────────────────────────────
story += [
    h1("Runbook Quality Tips"),
    hr(),
    p("The LLM confidence score is directly tied to runbook quality. "
      "Better runbooks = higher confidence = more incidents auto-closed without human intervention."),
    sp(),
    tbl([
        ["Tip", "Why It Matters"],
        ["Use exact transaction codes (ST22, SM50, WE02)",
         "LLM recognises SAP transactions and scores them as authoritative"],
        ["Include the error_code field exactly as SAP sends it",
         "Triggers the 0.85 confidence floor — biggest single confidence boost"],
        ["Add SAP Note numbers in references",
         "LLM treats SAP Notes as official documentation"],
        ["Set auto_close_eligible: false for security/auth errors",
         "Prevents accidental auto-closure of sensitive incidents"],
        ["Start new runbooks with auto_close_eligible: false",
         "Watch RCA quality for a week, then flip to true once you trust it"],
        ["Add real symptoms from your system logs",
         "Improves RAG retrieval — more specific = better runbook match"],
    ], [6.5*cm, 10*cm]),
    sp(20),
    hr(),
    note("SAP Self-Healing System — github.com/Sai6522/heal · Generated 2026-03-17"),
]

doc.build(story)
print(f"PDF created: {OUT}")
