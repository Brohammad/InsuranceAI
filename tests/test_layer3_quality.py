"""
tests/test_layer3_quality.py
──────────────────────────────
Layer 3 Quality & Safety — End-to-End Test

Loads all interactions from DB (written by Layer 2 dispatcher),
runs the full quality pipeline for each, and prints a Rich report.

Pipeline per interaction:
  1. CritiqueAgent.run()    → message quality review
  2. ComplianceAgent.check()→ IRDAI rules check
  3. SafetyAgent.check()    → distress / vulnerability detection
  4. SentimentAgent.analyse()→ customer intent & polarity
  5. QualityScoringAgent.score() → composite 0–100 + grade
  6. Save to quality_scores table

All agents run in mock mode (MOCK_DELIVERY=true in .env).
"""

from __future__ import annotations

import sqlite3
import json

from rich.console import Console
from rich.table import Table
from rich import box

from core.config import settings
from core.database import get_customer, get_policy
from agents.layer3_quality.critique_agent   import CritiqueAgent
from agents.layer3_quality.compliance_agent import ComplianceAgent
from agents.layer3_quality.safety_agent     import SafetyAgent, SafetyFlag
from agents.layer3_quality.sentiment_agent  import SentimentAgent, SentimentPolarity
from agents.layer3_quality.quality_scoring  import QualityScoringAgent


def load_interactions() -> list[dict]:
    """Load all interactions from DB."""
    conn = sqlite3.connect(str(settings.abs_db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT * FROM interactions
        ORDER BY sent_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def run_layer3_pipeline():
    console = Console()
    console.print("\n[bold cyan]Layer 3 Quality & Safety Pipeline — Test Run[/bold cyan]\n")

    interactions = load_interactions()
    console.print(f"Loaded [bold]{len(interactions)}[/bold] interactions from DB\n")

    if not interactions:
        console.print("[red]No interactions found. Run Layer 2 dispatcher first.[/red]")
        return

    # Initialise agents
    critique   = CritiqueAgent()
    compliance = ComplianceAgent()
    safety     = SafetyAgent()
    sentiment  = SentimentAgent()
    scorer     = QualityScoringAgent()

    results = []

    for iact in interactions:
        cust = get_customer(iact["customer_id"])
        pol  = get_policy(iact["policy_number"])
        if not cust or not pol:
            continue

        channel = iact["channel"]
        message = iact.get("message_content", "")

        # 1. Critique
        cr = critique.run(
            customer = cust,
            policy   = pol,
            message  = message,
            channel  = channel,
        )

        # 2. Compliance
        co = compliance.check(
            customer = cust,
            policy   = pol,
            message  = message,
            channel  = channel,
        )

        # 3. Safety
        sa = safety.check(
            customer   = cust,
            policy     = pol,
            journey_id = iact["journey_id"],
            message    = message,
        )

        # 4. Sentiment
        se = sentiment.analyse(
            customer = cust,
            policy   = pol,
            message  = message,
        )

        # 5. Quality Score
        qs = scorer.score(
            journey_id    = iact["journey_id"],
            policy_number = pol.policy_number,
            customer_name = cust.name,
            channel       = channel,
            critique      = cr,
            compliance    = co,
            safety        = sa,
            sentiment     = se,
        )

        # 6. Save to DB
        scorer.save_score(qs)

        results.append({
            "customer":    cust.name,
            "channel":     channel,
            "approved":    cr.approved,
            "compliance":  co.overall_pass,
            "safety_flag": sa.flag.value,
            "sentiment":   se.polarity.value,
            "score":       qs.total_score,
            "grade":       qs.grade,
        })

    # ── Results Table ─────────────────────────────────────────────────────────
    table = Table(
        "Customer", "Channel", "Critique", "Compliance",
        "Safety", "Sentiment", "Score", "Grade",
        box=box.ROUNDED,
        title=f"Layer 3 Quality Results — {len(results)} interactions",
    )

    PASS = "[green]✓[/]"
    FAIL = "[red]✗[/]"
    WARN = "[yellow]⚠[/]"

    grade_style = {"A": "bold green", "B": "green", "C": "yellow", "D": "orange3", "F": "red"}

    for r in results:
        safety_str = (
            PASS if r["safety_flag"] == "clear"
            else f"[red]{r['safety_flag']}[/]"
        )
        sentiment_str = (
            f"[green]{r['sentiment']}[/]" if r["sentiment"] == "positive"
            else f"[yellow]{r['sentiment']}[/]" if r["sentiment"] == "neutral"
            else f"[red]{r['sentiment']}[/]"
        )
        grade = r["grade"]
        score_str = f"[{grade_style.get(grade,'white')}]{r['score']:.0f}[/]"
        grade_str = f"[{grade_style.get(grade,'white')}]{grade}[/]"

        table.add_row(
            r["customer"],
            r["channel"],
            PASS if r["approved"]   else FAIL,
            PASS if r["compliance"] else WARN,
            safety_str,
            sentiment_str,
            score_str,
            grade_str,
        )

    console.print(table)

    # ── Summary stats ─────────────────────────────────────────────────────────
    total     = len(results)
    approved  = sum(1 for r in results if r["approved"])
    compliant = sum(1 for r in results if r["compliance"])
    safe      = sum(1 for r in results if r["safety_flag"] == "clear")
    positive  = sum(1 for r in results if r["sentiment"] == "positive")
    avg_score = sum(r["score"] for r in results) / total if total else 0
    grades    = {g: sum(1 for r in results if r["grade"] == g) for g in ["A","B","C","D","F"]}

    console.print(f"\n[bold]Quality Summary ({total} interactions):[/bold]")
    console.print(f"  Messages approved by Critique : {approved}/{total} ({approved/total*100:.0f}%)")
    console.print(f"  IRDAI Compliant               : {compliant}/{total} ({compliant/total*100:.0f}%)")
    console.print(f"  Safety Clear (no flags)        : {safe}/{total} ({safe/total*100:.0f}%)")
    console.print(f"  Positive Customer Sentiment    : {positive}/{total} ({positive/total*100:.0f}%)")
    console.print(f"  Average Quality Score          : {avg_score:.1f}/100")
    console.print(f"  Grade Distribution             : " + " | ".join(f"{g}:{n}" for g,n in grades.items() if n > 0))

    # Verify DB
    conn = sqlite3.connect(str(settings.abs_db_path))
    qs_count = conn.execute("SELECT COUNT(*) FROM quality_scores").fetchone()[0]
    conn.close()
    console.print(f"\n[bold green]✅ {qs_count} quality scores saved to DB.[/bold green]")


if __name__ == "__main__":
    run_layer3_pipeline()
