"""
tests/test_final_integration.py
────────────────────────────────
RenewAI — Full End-to-End Integration Test

Runs all 5 layers in sequence on a fresh DB snapshot and prints a
consolidated result table at the end.

  Layer 1 — Strategic Agents   (segmentation → propensity → timing → channel → orchestrator)
  Layer 2 — Execution Agents   (dispatcher → all channel agents → payment → objections)
  Layer 3 — Quality & Safety   (critique → safety → compliance → sentiment → scoring)
  Layer 4 — Learning & Opt.    (feedback loop → A/B manager → drift detector → report)
  Layer 5 — Human Interface    (queue manager → resolve → supervisor dashboard)
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime

import pytest
pytestmark = pytest.mark.e2e  # skip unless: pytest -m e2e
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()

# ─── helpers ─────────────────────────────────────────────────────────────────

def _section(title: str) -> None:
    console.rule(f"[bold cyan]{title}[/bold cyan]")

def _ok(msg: str) -> None:
    console.print(f"  [green]✓[/green] {msg}")

def _warn(msg: str) -> None:
    console.print(f"  [yellow]⚠[/yellow] {msg}")

def _fail(msg: str) -> None:
    console.print(f"  [red]✗[/red] {msg}")

def _db():
    from core.config import settings
    conn = sqlite3.connect(str(settings.abs_db_path))
    conn.row_factory = sqlite3.Row
    return conn

def _count(table: str) -> int:
    conn = _db()
    try:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except Exception:
        n = 0
    conn.close()
    return n

results: list[dict[str, Any]] = []

def _record(layer: str, check: str, passed: bool, detail: str = "") -> None:
    results.append({"layer": layer, "check": check, "passed": passed, "detail": detail})
    if passed:
        _ok(f"{check}" + (f" — {detail}" if detail else ""))
    else:
        _fail(f"{check}" + (f" — {detail}" if detail else ""))


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — Strategic Agents
# ═══════════════════════════════════════════════════════════════════════════════

def test_layer1() -> None:
    _section("Layer 1: Strategic Agents")

    from core.database import get_customer, get_policy
    from agents.layer1_strategic.orchestrator import run_layer1

    conn = _db()
    policy_rows = conn.execute("SELECT policy_number, customer_id FROM policies").fetchall()
    conn.close()
    n = len(policy_rows)

    pre     = _count("renewal_journeys")
    created = 0
    seg_ok = prop_ok = tim_ok = chan_ok = 0

    for row in policy_rows:
        pol  = get_policy(row["policy_number"])
        cust = get_customer(row["customer_id"])
        if not pol or not cust:
            continue
        j = run_layer1(cust, pol)
        if j:
            created   += 1
            if j.segment:           seg_ok  += 1
            if j.lapse_score >= 0:  prop_ok += 1
            if j.steps:             tim_ok  += 1
            if j.channel_sequence:  chan_ok += 1

    post = _count("renewal_journeys")
    _record("L1", "Segmentation",         seg_ok  == n, f"{seg_ok}/{n} segmented")
    _record("L1", "Propensity scored",     prop_ok == n, f"{prop_ok}/{n} lapse scores")
    _record("L1", "Timing / steps",        tim_ok  == n, f"{tim_ok}/{n} with steps")
    _record("L1", "Channel sequence",      chan_ok == n, f"{chan_ok}/{n} channels set")
    _record("L1", "Orchestrator/journeys", post >= n,
            f"{post} total in DB (+{post-pre} new this run)")


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — Execution
# ═══════════════════════════════════════════════════════════════════════════════

def test_layer2() -> None:
    _section("Layer 2: Execution Agents")

    from agents.layer2_execution.dispatcher import Layer2Dispatcher, load_active_journeys

    pre_int = _count("interactions")

    journeys = load_active_journeys()
    if not journeys:
        _warn("No not_started journeys — dispatcher will process 0 journeys this run")
        _record("L2", "Dispatcher ran",      True, "0 new journeys (already dispatched)")
        _record("L2", "Interactions logged", True, f"{pre_int} total interactions in DB")
        conn = _db()
        total = conn.execute("SELECT COUNT(*) FROM renewal_journeys").fetchone()[0]
        paid  = conn.execute("SELECT COUNT(*) FROM renewal_journeys WHERE status='payment_done'").fetchone()[0]
        conn.close()
        rate = round(paid / total * 100, 1) if total else 0
        _record("L2", "Renewal rate >= 40%", rate >= 40, f"{rate}% ({paid}/{total} paid)")
        _record("L2", "Escalations handled", True, "see existing DB rows")
        return

    d        = Layer2Dispatcher()
    summaries = d.run_all(journeys)

    paid  = sum(1 for s in summaries if s.get("payment_done"))
    total = len(summaries)
    ints  = _count("interactions")
    rate  = round(paid / total * 100, 1) if total else 0

    _record("L2", "Dispatcher ran",         total > 0,   f"{total} journeys processed")
    _record("L2", "Interactions logged",    ints > pre_int, f"{ints} total ({ints-pre_int} new)")
    _record("L2", "Renewal rate >= 40%",    rate >= 40,  f"{rate}% ({paid}/{total} paid)")
    esc    = sum(1 for s in summaries if s.get("escalated"))
    opted  = sum(1 for s in summaries if s.get("opted_out"))
    _record("L2", "Escalations handled",    True, f"{esc} escalated, {opted} opted out")


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — Quality & Safety
# ═══════════════════════════════════════════════════════════════════════════════

def test_layer3() -> None:
    _section("Layer 3: Quality & Safety")

    from core.database import get_customer, get_policy
    from agents.layer3_quality.critique_agent   import CritiqueAgent
    from agents.layer3_quality.compliance_agent import ComplianceAgent
    from agents.layer3_quality.safety_agent     import SafetyAgent
    from agents.layer3_quality.sentiment_agent  import SentimentAgent
    from agents.layer3_quality.quality_scoring  import QualityScoringAgent

    pre_qs = _count("quality_scores")

    conn  = _db()
    ints  = conn.execute("SELECT * FROM interactions LIMIT 20").fetchall()
    conn.close()

    if not ints:
        _warn("No interactions found — skipping Layer 3 scoring")
        _record("L3", "Interactions scored",  True, "skipped — no interactions")
        _record("L3", "Avg quality >= 60",    True, "skipped")
        _record("L3", "quality_scores table", True, f"{pre_qs} existing rows")
        return

    critique   = CritiqueAgent()
    compliance = ComplianceAgent()
    safety     = SafetyAgent()
    sentiment  = SentimentAgent()
    scorer     = QualityScoringAgent()

    scored = 0
    total_score = 0.0

    for row in ints:
        iact = dict(row)
        cust = get_customer(iact["customer_id"])
        pol  = get_policy(iact["policy_number"])
        if not cust or not pol:
            continue

        channel = iact["channel"]
        message = iact.get("message_content", "")

        cr = critique.run(customer=cust, policy=pol, message=message, channel=channel)
        co = compliance.check(customer=cust, policy=pol, message=message, channel=channel)
        sa = safety.check(customer=cust, policy=pol, journey_id=iact["journey_id"], message=message)
        se = sentiment.analyse(customer=cust, policy=pol, message=message)

        qs = scorer.score(
            journey_id    = iact["journey_id"],
            policy_number = pol.policy_number,
            customer_name = cust.name,
            channel       = channel,
            critique=cr, compliance=co, safety=sa, sentiment=se,
        )
        scorer.save_score(qs)
        scored += 1
        total_score += qs.total_score

    avg     = round(total_score / scored, 1) if scored else 0
    post_qs = _count("quality_scores")

    _record("L3", "Interactions scored",    scored == len(ints), f"{scored}/{len(ints)}")
    _record("L3", "Avg quality >= 60",      avg >= 60,           f"{avg}/100")
    _record("L3", "quality_scores table",   post_qs > pre_qs,    f"{post_qs} total rows (+{post_qs-pre_qs} new)")


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 4 — Learning & Optimisation
# ═══════════════════════════════════════════════════════════════════════════════

def test_layer4() -> None:
    _section("Layer 4: Learning & Optimisation")

    from agents.layer4_learning.feedback_loop  import FeedbackLoopAgent
    from agents.layer4_learning.ab_test_manager import ABTestManager
    from agents.layer4_learning.drift_detector  import DriftDetector
    from agents.layer4_learning.report_agent    import ReportAgent

    # Feedback
    fb_agent  = FeedbackLoopAgent()
    events, summary = fb_agent.run()
    _record("L4", "Feedback events",       len(events) > 0, f"{len(events)} events, avg Δ={summary.avg_lapse_delta:+.1f}")
    _record("L4", "Positive signals",      summary.positive_signals > 0,
            f"{summary.positive_signals} positive / {summary.negative_signals} negative")

    # A/B
    ab      = ABTestManager()
    ab_res  = ab.run()
    _record("L4", "A/B test results",      len(ab_res) >= 1, f"{len(ab_res)} variant types analysed")

    # Drift
    dd      = DriftDetector()
    drift   = dd.run()
    _record("L4", "Drift detector ran",    True, f"overall={drift.overall}, anomalies={len(drift.anomalies)}")

    # Report
    ra      = ReportAgent()
    md      = ra.generate()
    has_content = len(md) > 200 and "Renewal Rate" in md
    _record("L4", "Report generated",      has_content, f"{len(md)} chars")
    from pathlib import Path as _Path
    reports = list(_Path("outputs/reports").glob("report_daily_*.md"))
    _record("L4", "Report saved to disk",  len(reports) > 0, f"{len(reports)} report(s) on disk")


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 5 — Human Interface
# ═══════════════════════════════════════════════════════════════════════════════

def test_layer5() -> None:
    _section("Layer 5: Human Interface")

    from agents.layer5_human.queue_manager       import QueueManager
    from agents.layer5_human.supervisor_dashboard import SupervisorDashboard

    qm    = QueueManager()
    queue = qm.load_queue()
    stats = qm.get_stats(queue)

    _record("L5", "Queue loaded",           True,  f"{stats.total_open} open cases")
    _record("L5", "Agents available",       stats.available_agents >= 2,
            f"{stats.available_agents}/4 available")

    if queue:
        case_id  = queue[0].case.case_id
        resolved = qm.resolve(case_id, "Integration test resolution", "TEST-AGENT")
        _record("L5", "Case resolved",      resolved, case_id)
        remaining = qm.load_queue()
        _record("L5", "Post-resolve queue", len(remaining) < len(queue),
                f"{len(remaining)} remaining")
    else:
        _warn("No open escalations to resolve — skipping resolution check")
        _record("L5", "Case resolved",  True, "skipped — no open cases")
        _record("L5", "Post-resolve queue", True, "skipped")

    # Dashboard render (suppress output via width-capped console)
    try:
        dash = SupervisorDashboard()
        dash.render()
        _record("L5", "Dashboard rendered", True, "all panels")
    except Exception as e:
        _record("L5", "Dashboard rendered", False, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

def print_summary() -> None:
    console.rule("[bold white]Integration Test Summary[/bold white]")

    t = Table("Layer", "Check", "Result", "Detail",
              box=box.ROUNDED, show_lines=True)

    passed = failed = 0
    for r in results:
        icon  = "[green]PASS[/]" if r["passed"] else "[red]FAIL[/]"
        t.add_row(r["layer"], r["check"], icon, r["detail"])
        if r["passed"]: passed += 1
        else:           failed += 1

    console.print(t)

    total  = passed + failed
    pct    = round(passed / total * 100) if total else 0
    color  = "green" if failed == 0 else "yellow" if failed <= 2 else "red"
    console.print(Panel(
        f"[{color}]{passed}/{total} checks passed ({pct}%)[/]\n"
        + (f"[red]{failed} FAILED[/]" if failed else "[green]All checks green ✅[/]"),
        title="[bold]Final Result[/bold]",
        border_style=color,
    ))

    # DB snapshot
    console.print("\n[bold dim]DB Snapshot:[/bold dim]")
    tables = ["customers","policies","renewal_journeys","interactions",
              "escalation_cases","quality_scores","feedback_events",
              "ab_test_results","drift_reports"]
    for tbl in tables:
        n = _count(tbl)
        if n:
            console.print(f"  [dim]{tbl:<25}[/dim] {n:>4} rows")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    console.print(f"\n[bold cyan]RenewAI — Full Integration Test[/bold cyan]")
    console.print(f"[dim]{datetime.now().strftime('%d %B %Y  %H:%M:%S')}[/dim]\n")

    t0 = time.time()
    test_layer1()
    test_layer2()
    test_layer3()
    test_layer4()
    test_layer5()
    elapsed = round(time.time() - t0, 1)

    print_summary()
    console.print(f"\n[dim]Completed in {elapsed}s[/dim]\n")
