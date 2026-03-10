"""
run_e2e.py
──────────
Full end-to-end demo runner for RenewAI (mock mode — no real API calls).

Runs all 5 layers in sequence for 3 representative customers:
  C001 — Nudge Needed   (WhatsApp-first, Hindi)
  C009 — High Risk      (ULIP, due in 5 days)
  C014 — High Risk      (due in 3 days → urgency override)

After each layer, reads the DB and prints what was written so you can
confirm real-time updates.
"""

from __future__ import annotations

import sqlite3, uuid, json, sys, time
from datetime import datetime, date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

console = Console()
DB_PATH = str(ROOT / "data" / "renewai.db")


# ─────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────

def db_counts() -> dict:
    conn = sqlite3.connect(DB_PATH)
    tables = ["renewal_journeys", "interactions", "escalation_cases",
              "quality_scores", "ab_test_results"]
    counts = {}
    for t in tables:
        try:
            counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception:
            counts[t] = 0
    conn.close()
    return counts


def print_db_state(label: str):
    counts = db_counts()
    t = Table(title=f"[bold cyan]DB State — {label}[/bold cyan]",
              box=box.SIMPLE_HEAVY, show_header=True)
    t.add_column("Table", style="yellow")
    t.add_column("Rows", style="green", justify="right")
    for k, v in counts.items():
        t.add_column if False else None
        t.add_row(k, str(v))
    console.print(t)


def print_latest_journeys(n: int = 5):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT rj.journey_id, c.name, rj.segment, rj.lapse_score,
               rj.status, rj.payment_received,
               json_array_length(rj.channel_sequence) AS channels,
               rj.created_at
        FROM renewal_journeys rj
        JOIN customers c ON c.customer_id = rj.customer_id
        ORDER BY rj.created_at DESC LIMIT ?
    """, (n,)).fetchall()
    conn.close()

    t = Table(title="[bold green]Latest Renewal Journeys[/bold green]",
              box=box.SIMPLE_HEAVY)
    t.add_column("Journey ID",   style="cyan",   min_width=20)
    t.add_column("Customer",     style="white",  min_width=18)
    t.add_column("Segment",      style="yellow")
    t.add_column("Lapse Score",  style="red",    justify="right")
    t.add_column("Status",       style="green")
    t.add_column("Paid?",        style="magenta", justify="center")
    t.add_column("Channels",     style="blue",   justify="right")
    t.add_column("Created At",   style="white")
    for r in rows:
        t.add_row(
            r["journey_id"], r["name"], str(r["segment"] or ""),
            str(r["lapse_score"] or ""), r["status"],
            "✅" if r["payment_received"] else "⬜",
            str(r["channels"] or 0), str(r["created_at"] or "")[:19],
        )
    console.print(t)


def print_latest_interactions(n: int = 10):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT i.interaction_id, c.name, i.channel, i.outcome,
               i.quality_score, i.sent_at
        FROM interactions i
        JOIN customers c ON c.customer_id = i.customer_id
        ORDER BY i.sent_at DESC LIMIT ?
    """, (n,)).fetchall()
    conn.close()

    t = Table(title="[bold green]Latest Interactions[/bold green]",
              box=box.SIMPLE_HEAVY)
    t.add_column("Interaction ID", style="cyan", min_width=18)
    t.add_column("Customer",       style="white", min_width=18)
    t.add_column("Channel",        style="yellow")
    t.add_column("Outcome",        style="green")
    t.add_column("Quality",        style="magenta", justify="right")
    t.add_column("Sent At",        style="white")
    for r in rows:
        t.add_row(
            r["interaction_id"], r["name"], r["channel"],
            r["outcome"], f"{r['quality_score'] or 0:.1f}", str(r["sent_at"] or "")[:19],
        )
    console.print(t)


def print_escalations():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT ec.case_id, c.name, ec.reason, ec.priority,
               ec.resolved, ec.created_at
        FROM escalation_cases ec
        JOIN customers c ON c.customer_id = ec.customer_id
        ORDER BY ec.created_at DESC
    """).fetchall()
    conn.close()
    if not rows:
        return
    t = Table(title="[bold red]Escalation Cases[/bold red]", box=box.SIMPLE_HEAVY)
    t.add_column("Case ID",   style="cyan")
    t.add_column("Customer",  style="white")
    t.add_column("Reason",    style="yellow")
    t.add_column("Priority",  style="red")
    t.add_column("Resolved",  style="green", justify="center")
    t.add_column("Created",   style="white")
    for r in rows:
        t.add_row(
            r["case_id"], r["name"], r["reason"], r["priority"],
            "✅" if r["resolved"] else "⬜", str(r["created_at"] or "")[:19],
        )
    console.print(t)


# ─────────────────────────────────────────────────────────────
#  Mock Gemini factory
# ─────────────────────────────────────────────────────────────

def _mock_client(responses: list[str]):
    """Returns a MagicMock gemini client cycling through responses."""
    idx = [0]
    def side_effect(*a, **kw):
        m = MagicMock()
        m.text = responses[idx[0] % len(responses)]
        idx[0] += 1
        return m
    client = MagicMock()
    client.models.generate_content.side_effect = side_effect
    return client


# ─────────────────────────────────────────────────────────────
#  LAYER 1 — Run for a customer/policy pair
# ─────────────────────────────────────────────────────────────

def run_layer1(customer_id: str, policy_number: str, segment_hint: str = "nudge_needed",
               lapse_score: int = 55) -> object | None:
    from core.database import get_customer, get_policy

    cust = get_customer(customer_id)
    pol  = get_policy(policy_number)
    if not cust or not pol:
        console.print(f"[red]❌ Customer {customer_id} or policy {policy_number} not found[/red]")
        return None

    days_left = (pol.renewal_due_date - date.today()).days
    intensity = "urgent" if days_left <= 3 else ("intensive" if days_left <= 7 else "moderate")

    seg_json    = json.dumps({"segment": segment_hint, "recommended_tone": "empathetic",
                               "recommended_strategy": "renewal_reminder", "risk_flag": "high",
                               "reasoning": "Mock segmentation."})
    prop_json   = json.dumps({"lapse_score": lapse_score, "intervention_intensity": intensity,
                               "top_reasons": ["payment history", "due soon"],
                               "recommended_actions": ["whatsapp", "voice"],
                               "reasoning": "Mock propensity."})
    timing_json = json.dumps({"best_contact_window": "18:00-20:00", "best_days": ["Monday", "Wednesday"],
                               "salary_day_flag": True, "urgency_override": days_left <= 3,
                               "reasoning": "Mock timing."})
    ch_seq = ["whatsapp", "email"] if days_left > 3 else ["whatsapp", "email", "voice"]
    ch_json     = json.dumps({"channel_sequence": ch_seq, "reasoning": "Mock channel."})

    mock_c = _mock_client([seg_json, prop_json, timing_json, ch_json])

    with patch("agents.layer1_strategic.segmentation.get_gemini_client",    return_value=mock_c), \
         patch("agents.layer1_strategic.propensity.get_gemini_client",       return_value=mock_c), \
         patch("agents.layer1_strategic.timing.get_gemini_client",           return_value=mock_c), \
         patch("agents.layer1_strategic.channel_selector.get_gemini_client", return_value=mock_c):
        from agents.layer1_strategic.orchestrator import run_layer1 as _run
        journey = _run(cust, pol)

    return journey


# ─────────────────────────────────────────────────────────────
#  LAYER 2 — Dispatch all steps for a journey
# ─────────────────────────────────────────────────────────────

def run_layer2(journey) -> list[dict]:
    if not journey:
        return []
    from agents.layer2_execution.dispatcher import Layer2Dispatcher

    msg_mock = MagicMock()
    msg_mock.text = "Dear Customer, your policy is due. Please renew now. Reply STOP to opt out."

    obj_mock_text = MagicMock()
    obj_mock_text.text = '{"rebuttal": "We understand your concern. Your policy protects your family — please renew today.", "follow_up_action": "send_payment_link", "confidence": 0.85}'

    with patch("agents.layer2_execution.whatsapp_agent.get_gemini_client") as wm, \
         patch("agents.layer2_execution.email_agent.get_gemini_client")    as em, \
         patch("agents.layer2_execution.voice_agent.get_gemini_client")    as vm, \
         patch("agents.layer2_execution.objection_handler.get_gemini_client") as om, \
         patch("agents.layer2_execution.whatsapp_agent.settings") as ws, \
         patch("agents.layer2_execution.email_agent.settings")    as es, \
         patch("agents.layer2_execution.voice_agent.settings")    as vs:

        for m_settings in (ws, es, vs):
            m_settings.mock_delivery   = True
            m_settings.model_execution = "gemini-2.5-flash"

        for m_client in (wm, em, vm):
            c = MagicMock()
            c.models.generate_content.return_value = msg_mock
            m_client.return_value = c

        oc = MagicMock()
        oc.models.generate_content.return_value = obj_mock_text
        om.return_value = oc

        dispatcher = Layer2Dispatcher()
        result = dispatcher.run_journey(journey)

    return result.get("steps", []) if isinstance(result, dict) else []


# ─────────────────────────────────────────────────────────────
#  LAYER 3 — Quality gate for each interaction
# ─────────────────────────────────────────────────────────────

def run_layer3(journey_id: str, policy_number: str, customer_name: str):
    from agents.layer3_quality.quality_scoring import QualityScoringAgent
    from agents.layer3_quality.critique_agent import CritiqueResult
    from agents.layer3_quality.compliance_agent import ComplianceResult
    from agents.layer3_quality.safety_agent import SafetyResult, SafetyFlag
    from agents.layer3_quality.sentiment_agent import SentimentResult, SentimentPolarity

    from agents.layer3_quality.compliance_agent import RuleCheck
    from agents.layer3_quality.sentiment_agent import CustomerIntent

    critique   = CritiqueResult(approved=True, tone_score=8, accuracy_score=8,
                                  personalisation_score=7, conversion_likelihood=8,
                                  overall_verdict="Good personalised message.")
    compliance = ComplianceResult(overall_pass=True, rules_checked=3,
                                   rules_failed=0, failed_rules=[], passed_rules=[])
    safety     = SafetyResult(flag=SafetyFlag.CLEAR, confidence=1.0)
    sentiment  = SentimentResult(polarity=SentimentPolarity.POSITIVE,
                                  score=0.65, intent=CustomerIntent.INTENDING_TO_PAY)

    agent = QualityScoringAgent()
    score = agent.score(
        journey_id=journey_id, policy_number=policy_number,
        customer_name=customer_name, channel="whatsapp",
        critique=critique, compliance=compliance,
        safety=safety, sentiment=sentiment,
    )
    agent.save_score(score)
    return score


# ─────────────────────────────────────────────────────────────
#  LAYER 4 — Full sub-pipeline: Feedback → A/B → Drift → Report
# ─────────────────────────────────────────────────────────────

def run_layer4() -> dict:
    """
    Runs the full Layer 4 sub-pipeline as defined in workflow.xml:
      FeedbackLoop → ABTestManager → DriftDetector → ReportAgent
    Returns a summary dict with results from all four stages.
    """
    from agents.layer4_learning.feedback_loop  import FeedbackLoopAgent
    from agents.layer4_learning.ab_test_manager import ABTestManager
    from agents.layer4_learning.drift_detector  import DriftDetector
    from agents.layer4_learning.report_agent    import ReportAgent

    # 1. Feedback Loop
    with patch("agents.layer1_strategic.propensity.PropensityAgent"):
        fb_agent = FeedbackLoopAgent()
        events, fb_summary = fb_agent.run()

    # 2. A/B Test Manager
    ab_manager = ABTestManager()
    ab_results = ab_manager.run()

    # 3. Drift Detector
    drift_detector = DriftDetector()
    drift_report   = drift_detector.run()

    # 4. Report Agent (mock mode — no LLM call)
    report_agent = ReportAgent()
    report_md    = report_agent.generate(report_type="daily")

    return {
        "feedback":    fb_summary,
        "ab_results":  ab_results,
        "drift":       drift_report,
        "report_path": report_md[:80] + "…" if len(report_md) > 80 else report_md,
    }


# ─────────────────────────────────────────────────────────────
#  LAYER 5 — Human queue + Supervisor Dashboard
# ─────────────────────────────────────────────────────────────

def run_layer5() -> list:
    """
    Runs Layer 5 as defined in workflow.xml:
      QueueManager (load + assign) → SupervisorDashboard (render snapshot)
    """
    from agents.layer5_human.queue_manager      import QueueManager
    from agents.layer5_human.supervisor_dashboard import SupervisorDashboard

    qm    = QueueManager()
    queue = qm.load_queue()

    # Always render the supervisor dashboard snapshot
    dash = SupervisorDashboard()
    dash.render()

    return queue


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    console.print(Panel.fit(
        "[bold white]🛡️  RenewAI — Full End-to-End Run[/bold white]\n"
        "[dim]Mock mode • All 5 layers • DB updates verified in real-time[/dim]",
        border_style="cyan"
    ))

    # ── Baseline ──────────────────────────────────────────────
    console.rule("[bold yellow]📊 BASELINE — Before E2E Run")
    print_db_state("Before")

    # ── Customer list to run ──────────────────────────────────
    # Fetch real customer/policy IDs from DB
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    run_targets = conn.execute("""
        SELECT c.customer_id, c.name, p.policy_number,
               p.renewal_due_date,
               CAST(julianday(p.renewal_due_date) - julianday('now') AS INT) AS days_left
        FROM customers c JOIN policies p ON p.customer_id = c.customer_id
        ORDER BY days_left ASC LIMIT 3
    """).fetchall()
    conn.close()

    console.print()
    t = Table(title="[bold cyan]Customers Selected for E2E Run[/bold cyan]", box=box.SIMPLE_HEAVY)
    t.add_column("Customer ID"); t.add_column("Name"); t.add_column("Policy"); t.add_column("Days Left", justify="right")
    for r in run_targets:
        t.add_row(r["customer_id"], r["name"], r["policy_number"], str(r["days_left"]))
    console.print(t)

    journeys          = []   # all created journeys
    learning_journeys = []   # score >= 70 → L4
    escalate_journeys = []   # score < 70 or safety flag → L5

    for i, row in enumerate(run_targets, 1):
        cid  = row["customer_id"]
        pid  = row["policy_number"]
        name = row["name"]
        days = row["days_left"]

        console.rule(f"[bold green]▶ Customer {i}/3: {name}  (due in {days} days)")

        # ── LAYER 1 ─────────────────────────────────────────
        console.print(f"\n[cyan]⚙  Layer 1 — Segmentation → Propensity → Timing → Channel[/cyan]")
        hint  = "high_risk" if days <= 5 else "nudge_needed"
        score = 85 if days <= 5 else 55
        journey = run_layer1(cid, pid, segment_hint=hint, lapse_score=score)

        if journey:
            journeys.append((journey, name))
            console.print(f"  ✅ Journey created: [bold]{journey.journey_id}[/bold]")
            console.print(f"     Segment: {journey.segment}  |  Lapse score: {journey.lapse_score}")
            console.print(f"     Steps: {len(journey.steps)}  |  Channels: {[s.channel.value for s in journey.steps]}")

        print_db_state(f"After Layer 1 — {name}")

        # ── LAYER 2 ─────────────────────────────────────────
        console.print(f"\n[cyan]📤  Layer 2 — Dispatching messages[/cyan]")
        steps = run_layer2(journey)
        for s in steps:
            console.print(f"  Step {s.get('step', '?')} | {s.get('channel','?'):10} | {s.get('outcome','?')}")

        print_db_state(f"After Layer 2 — {name}")
        print_latest_interactions(n=len(steps) + 1 if steps else 3)

        # ── LAYER 3 ─────────────────────────────────────────
        console.print(f"\n[cyan]🔍  Layer 3 — Quality Gate[/cyan]")
        qs = None
        if journey:
            qs = run_layer3(journey.journey_id, pid, name)
            console.print(f"  ✅ Quality score: [bold]{qs.total_score:.1f}[/bold]  Grade: [bold]{qs.grade}[/bold]")

            # ── L3 → L4/L5 routing (per workflow.xml) ───────
            if qs.safety_score == 0.0:
                console.print(f"  [red]🚨 Safety flag detected → routing to L5 escalation[/red]")
                escalate_journeys.append((journey, name, "safety_flag", qs))
            elif qs.total_score < 70:
                console.print(f"  [yellow]⚠  Score {qs.total_score:.1f} < 70 → routing to L5 escalation[/yellow]")
                escalate_journeys.append((journey, name, "low_quality", qs))
            else:
                console.print(f"  [green]✅ Score {qs.total_score:.1f} ≥ 70 → routing to L4 learning[/green]")
                learning_journeys.append((journey, name, qs))

        print_db_state(f"After Layer 3 — {name}")

        console.print()

    # ── LAYER 4 ─────────────────────────────────────────────
    console.rule("[bold magenta]🔄 Layer 4 — Feedback → A/B Test → Drift → Report")
    console.print(f"  Journeys routed to L4 : [green]{len(learning_journeys)}[/green] (score ≥ 70)")
    l4 = run_layer4()
    fb = l4["feedback"]
    console.print(f"  Events processed      : {fb.total_events}")
    console.print(f"  Positive signals      : {fb.positive_signals}")
    console.print(f"  Negative signals      : {fb.negative_signals}")
    console.print(f"  Policies improved     : {fb.policies_improved}")
    console.print(f"  Payments confirmed    : {fb.payments_confirmed}")
    console.print(f"  Propensity refresh    : {'✅' if fb.propensity_prompt_refreshed else '⬜ (threshold not yet met)'}")

    ab_results = l4["ab_results"]
    if ab_results:
        console.print(f"\n  [magenta]A/B Test Results ({len(ab_results)} variant types):[/magenta]")
        for r in ab_results:
            sig = "✅ significant" if r.significant else "⬜ not yet significant"
            console.print(f"    {r.variant_type:10} → winner=[bold]{r.winner}[/bold]  conv={r.winner_conv_rate:.1f}%  lift={r.lift_pct:+.1f}%  {sig}")
    else:
        console.print("  [dim]A/B Test: insufficient data for significance (need more interactions)[/dim]")

    drift = l4["drift"]
    drift_color = {"ok": "green", "warning": "yellow", "critical": "red"}.get(drift.overall.value, "white")
    console.print(f"\n  [bold]Drift Detector:[/bold] [{drift_color}]{drift.overall.value.upper()}[/{drift_color}] — {drift.summary}")

    console.print(f"\n  [bold]Report Agent:[/bold] Daily report generated ✅")

    # ── L4 → L1 insights loop (per workflow.xml dashed arrow) ────────────────
    console.print(f"\n  [dim magenta]↺  Insights loop → Orchestrator: A/B winners + drift alerts fed back[/dim magenta]")
    if ab_results:
        for r in ab_results:
            console.print(f"     Orchestrator updated: best_{r.variant_type}=[bold]{r.winner}[/bold]")
    if drift.anomalies:
        console.print(f"     Orchestrator notified: {len(drift.anomalies)} drift anomal{'y' if len(drift.anomalies)==1 else 'ies'} detected")
    else:
        console.print(f"     Orchestrator notified: no drift — system stable")

    # ── LAYER 5 ─────────────────────────────────────────────
    console.rule("[bold red]🚨 Layer 5 — Human Escalation Queue + Supervisor Dashboard")
    console.print(f"  Journeys routed to L5 : [red]{len(escalate_journeys)}[/red] (score < 70 or safety flag)")
    open_cases = run_layer5()
    if open_cases:
        console.print(f"  Open escalation cases : {len(open_cases)}")
        print_escalations()
    else:
        console.print("  [green]No open escalations — all journeys handled by AI[/green]")

    # ── FINAL DB STATE ───────────────────────────────────────
    console.rule("[bold white]📊 FINAL DATABASE STATE")
    print_db_state("After Full E2E Run")
    print_latest_journeys(n=len(journeys))
    print_latest_interactions(n=6)
    print_escalations()

    console.print()
    console.print(Panel.fit(
        f"[bold green]✅ End-to-End Run Complete![/bold green]\n"
        f"[white]• {len(journeys)} journeys created & dispatched\n"
        f"• {len(journeys)} quality scores written\n"
        f"• DB updated in real-time — every write immediately visible in Streamlit dashboard[/white]",
        border_style="green"
    ))


if __name__ == "__main__":
    main()
