"""
agents/layer5_human/supervisor_dashboard.py
────────────────────────────────────────────
Supervisor Dashboard — Rich CLI

A comprehensive live terminal dashboard for renewal operations supervisors.
Displays all key metrics from all 5 layers in one view.

Sections:
  Panel A — Portfolio Overview (renewal rate, premium, journeys)
  Panel B — Escalation Queue (open cases, SLA status, agent load)
  Panel C — Quality Metrics (avg score, grade dist, drift alerts)
  Panel D — A/B Test Leaderboard (best channel/tone/strategy)
  Panel E — Top 5 At-Risk Policies
  Panel F — Recent Activity Feed (last 10 interactions)
  Panel G — Agent Workload
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich import box
from loguru import logger

from core.config import settings
from agents.layer5_human.queue_manager import QueueManager, MOCK_AGENTS


# ── DB helpers ────────────────────────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(settings.abs_db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _get_portfolio() -> dict:
    conn = _db()
    total    = conn.execute("SELECT COUNT(*) FROM renewal_journeys").fetchone()[0]
    paid     = conn.execute("SELECT COUNT(*) FROM renewal_journeys WHERE status='payment_done'").fetchone()[0]
    in_prog  = conn.execute("SELECT COUNT(*) FROM renewal_journeys WHERE status='in_progress'").fetchone()[0]
    opted    = conn.execute("SELECT COUNT(*) FROM renewal_journeys WHERE status='opted_out'").fetchone()[0]
    esc      = conn.execute("SELECT COUNT(*) FROM renewal_journeys WHERE status='escalated'").fetchone()[0]
    p_rows   = conn.execute("""
        SELECT p.annual_premium FROM renewal_journeys j
        JOIN policies p ON j.policy_number=p.policy_number
        WHERE j.status='payment_done'
    """).fetchall()
    premium  = sum(r[0] for r in p_rows)
    total_int= conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
    conn.close()
    return {
        "total": total, "paid": paid, "in_progress": in_prog,
        "opted_out": opted, "escalated": esc,
        "renewal_rate": round(paid / total * 100, 1) if total else 0,
        "premium": premium, "interactions": total_int,
    }


def _get_quality() -> dict:
    conn = _db()
    try:
        row = conn.execute("""
            SELECT AVG(total_score), AVG(critique_score), AVG(compliance_score),
                   AVG(safety_score), AVG(sentiment_score), COUNT(*)
            FROM quality_scores
        """).fetchone()
        grades = dict(conn.execute(
            "SELECT grade, COUNT(*) FROM quality_scores GROUP BY grade"
        ).fetchall())
    except sqlite3.OperationalError:
        conn.close()
        return {}
    conn.close()
    return {
        "avg": round(row[0] or 0, 1), "critique": round(row[1] or 0, 1),
        "compliance": round(row[2] or 0, 1), "safety": round(row[3] or 0, 1),
        "sentiment": round(row[4] or 0, 1), "total": row[5] or 0,
        "grades": grades,
    }


def _get_escalations() -> list[dict]:
    conn = _db()
    try:
        rows = conn.execute("""
            SELECT case_id, policy_number, customer_id, reason, priority,
                   assigned_to, agent_name, resolved, created_at
            FROM escalation_cases WHERE resolved = 0
            ORDER BY CASE priority
                WHEN 'p1_urgent' THEN 0 WHEN 'p2_high' THEN 1
                WHEN 'p3_normal' THEN 2 ELSE 3 END
        """).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return []
    conn.close()
    return [dict(r) for r in rows]


def _get_ab_winners() -> list[dict]:
    conn = _db()
    try:
        rows = conn.execute("""
            SELECT variant_type, winner, winner_conv_rate, lift_pct, significant
            FROM ab_test_results ORDER BY run_at DESC LIMIT 3
        """).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return []
    conn.close()
    return [dict(r) for r in rows]


def _get_at_risk() -> list[dict]:
    conn = _db()
    rows = conn.execute("""
        SELECT j.policy_number, c.name, j.lapse_score, j.segment, j.status
        FROM renewal_journeys j
        JOIN customers c ON j.customer_id = c.customer_id
        WHERE j.status != 'payment_done' AND j.lapse_score >= 50
        ORDER BY j.lapse_score DESC LIMIT 5
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_recent_interactions() -> list[dict]:
    conn = _db()
    rows = conn.execute("""
        SELECT i.channel, c.name, i.outcome, i.sent_at
        FROM interactions i
        JOIN customers c ON i.customer_id = c.customer_id
        ORDER BY i.sent_at DESC LIMIT 10
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_drift() -> dict:
    conn = _db()
    try:
        row = conn.execute(
            "SELECT overall, summary FROM drift_reports ORDER BY run_at DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        conn.close()
        return {"overall": "ok", "summary": "No drift data"}
    conn.close()
    return dict(row) if row else {"overall": "ok", "summary": "No drift data"}


# ── Panel builders ────────────────────────────────────────────────────────────

def _portfolio_panel(data: dict) -> Panel:
    t = Table(show_header=False, box=None, padding=(0, 1))
    rate_color = "green" if data["renewal_rate"] >= 50 else "yellow" if data["renewal_rate"] >= 35 else "red"
    t.add_row("Renewal Rate",        f"[{rate_color}]{data['renewal_rate']}%[/]")
    t.add_row("Premium Recovered",   f"[bold green]₹{data['premium']:,.0f}[/]")
    t.add_row("Total Journeys",      str(data["total"]))
    t.add_row("Payments Received",   f"[green]{data['paid']}[/]")
    t.add_row("In Progress",         f"[yellow]{data['in_progress']}[/]")
    t.add_row("Opted Out",           f"[dim]{data['opted_out']}[/]")
    t.add_row("Escalated",           f"[red]{data['escalated']}[/]")
    t.add_row("Total Interactions",  str(data["interactions"]))
    return Panel(t, title="[bold]Portfolio Overview[/]", border_style="blue")


def _quality_panel(data: dict) -> Panel:
    if not data:
        return Panel("[dim]No quality data yet[/]", title="Quality Metrics", border_style="blue")
    t = Table(show_header=False, box=None, padding=(0, 1))
    score = data["avg"]
    sc = "green" if score >= 80 else "yellow" if score >= 65 else "red"
    t.add_row("Avg Quality Score",  f"[{sc}]{score}/100[/]")
    t.add_row("Critique",           f"{data['critique']}/100")
    t.add_row("Compliance (IRDAI)", f"{data['compliance']}/100")
    t.add_row("Safety",             f"{data['safety']}/100")
    t.add_row("Sentiment",          f"{data['sentiment']}/100")
    t.add_row("Scored",             str(data["total"]))
    grades = data.get("grades", {})
    t.add_row("Grades", " ".join(f"{g}:{n}" for g, n in sorted(grades.items()) if n))
    return Panel(t, title="[bold]Quality Metrics[/]", border_style="magenta")


def _escalation_panel(cases: list[dict]) -> Panel:
    if not cases:
        return Panel("[green]✓ Queue empty — no open escalations[/]", title="[bold]Escalation Queue[/]", border_style="green")
    t = Table("Case", "Policy", "Reason", "Priority", "Agent", box=box.SIMPLE, show_header=True)
    priority_colors = {"p1_urgent": "red", "p2_high": "orange3", "p3_normal": "yellow", "p4_low": "dim"}
    for c in cases:
        pcolor = priority_colors.get(c["priority"], "white")
        t.add_row(
            c["case_id"][-8:],
            c["policy_number"],
            c["reason"],
            f"[{pcolor}]{c['priority'].upper()}[/]",
            c["agent_name"] or "[dim]unassigned[/]",
        )
    return Panel(t, title=f"[bold]Escalation Queue[/] ({len(cases)} open)", border_style="red")


def _ab_panel(winners: list[dict]) -> Panel:
    if not winners:
        return Panel("[dim]No A/B results yet[/]", title="A/B Test Winners", border_style="blue")
    t = Table("Type", "Winner", "Conv%", "Lift", "Sig", box=box.SIMPLE)
    for r in winners:
        sig = "[green]✓[/]" if r["significant"] else "[yellow]⚠[/]"
        t.add_row(r["variant_type"].upper(), f"[bold]{r['winner']}[/]",
                  f"{r['winner_conv_rate']:.1f}%", f"{r['lift_pct']:+.1f}%", sig)
    return Panel(t, title="[bold]A/B Test Winners[/]", border_style="cyan")


def _at_risk_panel(policies: list[dict]) -> Panel:
    if not policies:
        return Panel("[green]No high-risk unpaid policies[/]", title="At-Risk Policies", border_style="green")
    t = Table("Policy", "Customer", "Score", "Segment", "Status", box=box.SIMPLE)
    for p in policies:
        score = p["lapse_score"]
        sc = "red" if score >= 80 else "orange3" if score >= 60 else "yellow"
        t.add_row(p["policy_number"], p["name"], f"[{sc}]{score:.0f}[/]", p["segment"], p["status"])
    return Panel(t, title="[bold]Top At-Risk Policies[/]", border_style="yellow")


def _activity_panel(interactions: list[dict]) -> Panel:
    if not interactions:
        return Panel("[dim]No interactions yet[/]", title="Recent Activity", border_style="blue")
    t = Table("Time", "Customer", "Channel", "Outcome", box=box.SIMPLE, show_header=True)
    outcome_colors = {
        "payment_made": "green", "responded": "cyan", "read": "blue",
        "opt_out": "red", "objection": "yellow", "no_response": "dim",
        "escalated": "orange3",
    }
    for i in interactions:
        ts = (i["sent_at"] or "")[:16].replace("T", " ")
        oc = i["outcome"] or "unknown"
        c  = outcome_colors.get(oc, "white")
        t.add_row(ts, i["name"], i["channel"], f"[{c}]{oc}[/]")
    return Panel(t, title="[bold]Recent Activity (last 10)[/]", border_style="blue")


def _agents_panel() -> Panel:
    t = Table("ID", "Name", "Available", "Load", box=box.SIMPLE)
    for a in MOCK_AGENTS:
        avail = "[green]✓ YES[/]" if a["available"] else "[red]✗ NO[/]"
        load_bar = "█" * a["load"]
        t.add_row(a["id"], a["name"], avail, f"{load_bar} {a['load']}")
    return Panel(t, title="[bold]Agent Workload[/]", border_style="blue")


def _drift_panel(drift: dict) -> Panel:
    overall = drift.get("overall", "ok").upper()
    colors  = {"OK": "green", "WARNING": "yellow", "CRITICAL": "red"}
    icons   = {"OK": "✅", "WARNING": "⚠️", "CRITICAL": "🚨"}
    c = colors.get(overall, "white")
    icon = icons.get(overall, "ℹ️")
    summary = drift.get("summary", "")
    return Panel(
        f"[{c}]{icon} {overall}[/{c}]\n{summary}",
        title="[bold]Drift Status[/]",
        border_style=c,
    )


# ── Main dashboard ────────────────────────────────────────────────────────────

class SupervisorDashboard:
    """Renders a full Rich CLI dashboard for the supervisor."""

    def __init__(self):
        self.console = Console()
        self.qm      = QueueManager()
        logger.info("SupervisorDashboard ready")

    def render(self) -> None:
        """Render the full dashboard once (static snapshot)."""
        portfolio   = _get_portfolio()
        quality     = _get_quality()
        escalations = _get_escalations()
        ab_winners  = _get_ab_winners()
        at_risk     = _get_at_risk()
        activity    = _get_recent_interactions()
        drift       = _get_drift()

        queue = self.qm.load_queue()

        ts = datetime.now().strftime("%d %B %Y %H:%M:%S")
        self.console.print(f"\n[bold cyan]═══ RenewAI Supervisor Dashboard ══════ {ts} ═══[/bold cyan]\n")

        # Row 1: Portfolio + Quality + Drift
        self.console.print(Columns([
            _portfolio_panel(portfolio),
            _quality_panel(quality),
            _drift_panel(drift),
        ], equal=True, expand=True))

        # Row 2: Escalation queue (full width)
        self.console.print(_escalation_panel(escalations))

        # Row 3: At-Risk + A/B Winners
        self.console.print(Columns([
            _at_risk_panel(at_risk),
            _ab_panel(ab_winners),
        ], equal=True, expand=True))

        # Row 4: Activity Feed + Agent Workload
        self.console.print(Columns([
            _activity_panel(activity),
            _agents_panel(),
        ], equal=True, expand=True))

        # Queue briefs for open cases
        if queue:
            self.console.print("\n[bold]Agent Briefs:[/bold]")
            for item in queue:
                p_colors = {
                    "p1_urgent": "red", "p2_high": "orange3",
                    "p3_normal": "yellow", "p4_low": "dim",
                }
                pcolor = p_colors.get(item.case.priority.value, "white")
                sla_str = (
                    f"[red]SLA BREACHED[/]" if item.sla_breached
                    else f"SLA: {item.sla_deadline.strftime('%H:%M') if item.sla_deadline else 'N/A'}"
                )
                self.console.print(Panel(
                    item.brief,
                    title=(
                        f"[{pcolor}]{item.case.priority.value.upper()}[/] | "
                        f"{item.case.case_id} | {item.case.reason.value} | "
                        f"Assigned: {item.agent_name or 'unassigned'} | {sla_str}"
                    ),
                    border_style=pcolor,
                ))
