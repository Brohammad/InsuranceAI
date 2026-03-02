"""
tests/test_layer4_learning.py
───────────────────────────────
Layer 4 Learning & Optimization — End-to-End Test

Runs the full learning pipeline in sequence:
  1. FeedbackLoopAgent  → update lapse scores from outcomes
  2. ABTestManager      → find best channel / tone / strategy
  3. DriftDetector      → check for anomalies
  4. ReportAgent        → generate Markdown daily report

Prints Rich-formatted results for each step, then the full report.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from agents.layer4_learning.feedback_loop  import FeedbackLoopAgent
from agents.layer4_learning.ab_test_manager import ABTestManager
from agents.layer4_learning.drift_detector  import DriftDetector, DriftSeverity
from agents.layer4_learning.report_agent    import ReportAgent


def run_layer4():
    console = Console()
    console.print("\n[bold cyan]Layer 4 Learning & Optimization — Full Pipeline Test[/bold cyan]\n")

    # ── 1. Feedback Loop ──────────────────────────────────────────────────────
    console.print("[bold]Step 1: Feedback Loop Agent[/bold]")
    fb_agent = FeedbackLoopAgent()
    events, summary = fb_agent.run()

    fb_table = Table("Metric", "Value", box=box.SIMPLE, show_header=True)
    fb_table.add_row("Total feedback events",  str(summary.total_events))
    fb_table.add_row("Positive signals (↓ lapse)", str(summary.positive_signals))
    fb_table.add_row("Negative signals (↑ lapse)", str(summary.negative_signals))
    fb_table.add_row("Avg lapse score delta",  f"{summary.avg_lapse_delta:+.1f}")
    fb_table.add_row("Policies improved",      str(summary.policies_improved))
    fb_table.add_row("Policies worsened",      str(summary.policies_worsened))
    fb_table.add_row("Payments confirmed",     str(summary.payments_confirmed))
    fb_table.add_row("Opt-outs",               str(summary.opt_outs))
    fb_table.add_row("Escalations",            str(summary.escalations))
    console.print(fb_table)

    # ── 2. A/B Test Manager ───────────────────────────────────────────────────
    console.print("\n[bold]Step 2: A/B Test Manager[/bold]")
    ab_manager = ABTestManager()
    ab_results = ab_manager.run()

    ab_table = Table(
        "Variant", "Winner", "Conv%", "Runner-Up", "Conv%", "Lift", "Significant",
        box=box.ROUNDED, title="A/B Test Results",
    )
    for r in ab_results:
        sig_str = "[green]✓ YES[/]" if r.significant else "[yellow]⚠ no[/]"
        ab_table.add_row(
            r.variant_type.upper(),
            f"[bold]{r.winner}[/]",
            f"{r.winner_conv_rate:.1f}%",
            r.runner_up,
            f"{r.runner_up_rate:.1f}%",
            f"{r.lift_pct:+.1f}%",
            sig_str,
        )
    console.print(ab_table)

    # Print all variant breakdown
    for r in ab_results:
        console.print(f"\n  [dim]{r.variant_type.title()} breakdown:[/dim]")
        for v in r.all_variants:
            bar = "█" * int(v.conversion_rate / 5)
            console.print(
                f"    {v.variant_name:<20} {bar:<20} "
                f"conv={v.conversion_rate:4.1f}%  eng={v.engagement_rate:4.1f}%  n={v.total}"
            )

    # ── 3. Drift Detector ─────────────────────────────────────────────────────
    console.print("\n[bold]Step 3: Drift Detector[/bold]")
    detector = DriftDetector()
    drift_report = detector.run()

    sev_color = {
        DriftSeverity.OK:       "green",
        DriftSeverity.WARNING:  "yellow",
        DriftSeverity.CRITICAL: "red",
    }
    color = sev_color[drift_report.overall]
    console.print(
        Panel(
            f"[{color}]{drift_report.summary}[/{color}]\n\n"
            + (
                "\n".join(
                    f"  [{sev_color[a.severity]}]{a.check_name}[/] | "
                    f"{a.metric}={a.current_val} (threshold={a.threshold}) | "
                    f"{a.description[:80]}..."
                    for a in drift_report.anomalies
                )
                or "  No anomalies detected."
            ),
            title=f"Drift Report — [{color}]{drift_report.overall.value.upper()}[/{color}]",
            border_style=color,
        )
    )

    # ── 4. Report Agent ───────────────────────────────────────────────────────
    console.print("\n[bold]Step 4: Report Agent — Generating Daily Report[/bold]")
    reporter = ReportAgent()
    md = reporter.generate(report_type="daily")

    # Show first 60 lines of report
    lines = md.split("\n")
    preview = "\n".join(lines[:60])
    console.print(Panel(preview, title="Daily Report Preview (first 60 lines)", border_style="cyan"))

    # Final summary
    console.print(f"\n[bold green]✅ Layer 4 complete![/bold green]")
    console.print(f"   Feedback events logged : {summary.total_events}")
    console.print(f"   A/B tests completed    : {len(ab_results)}")
    console.print(f"   Drift checks run       : {len(DriftDetector.CHECKS)}")
    console.print(f"   Anomalies detected     : {len(drift_report.anomalies)}")
    console.print(f"   Report saved to        : outputs/reports/")


if __name__ == "__main__":
    run_layer4()
