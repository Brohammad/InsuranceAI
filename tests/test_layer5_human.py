"""
tests/test_layer5_human.py
───────────────────────────
Layer 5 Human Interface — End-to-End Test

1. QueueManager   — loads open escalations, assigns agents, generates briefs
2. Mock resolution — resolves a case, verifies DB update
3. SupervisorDashboard — renders full dashboard
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich import box

from agents.layer5_human.queue_manager      import QueueManager
from agents.layer5_human.supervisor_dashboard import SupervisorDashboard


def run_layer5():
    console = Console()
    console.print("\n[bold cyan]Layer 5 Human Interface — Test Run[/bold cyan]\n")

    # ── 1. Queue Manager ──────────────────────────────────────────────────────
    console.print("[bold]Step 1: Queue Manager — Loading escalations[/bold]")
    qm    = QueueManager()
    queue = qm.load_queue()
    stats = qm.get_stats(queue)

    qt = Table("Metric", "Value", box=box.SIMPLE)
    qt.add_row("Total open cases",   str(stats.total_open))
    qt.add_row("P1 Urgent",          f"[red]{stats.p1_count}[/]")
    qt.add_row("P2 High",            f"[orange3]{stats.p2_count}[/]")
    qt.add_row("P3 Normal",          f"[yellow]{stats.p3_count}[/]")
    qt.add_row("P4 Low",             f"[dim]{stats.p4_count}[/]")
    qt.add_row("SLA Breached",       f"[red]{stats.sla_breached}[/]" if stats.sla_breached else "0")
    qt.add_row("Assigned",           str(stats.assigned))
    qt.add_row("Unassigned",         str(stats.unassigned))
    qt.add_row("Available agents",   str(stats.available_agents))
    console.print(qt)

    if queue:
        console.print(f"\n[bold]Open Cases ({len(queue)}):[/bold]")
        for item in queue:
            console.print(
                f"  [{item.case.priority.value}] {item.case.case_id} | "
                f"reason={item.case.reason.value} | "
                f"agent={item.agent_name or 'unassigned'} | "
                f"policy={item.case.policy_number}"
            )
            console.print(f"  Brief: [dim]{item.brief[:100]}...[/dim]" if len(item.brief) > 100 else f"  Brief: {item.brief}")

        # ── 2. Mock resolution ─────────────────────────────────────────────
        console.print(f"\n[bold]Step 2: Resolving first case ({queue[0].case.case_id})[/bold]")
        resolved = qm.resolve(
            case_id         = queue[0].case.case_id,
            resolution_note = "Spoke with customer. Offered 30-day payment extension. Customer agreed to pay within 7 days.",
            resolved_by     = "AGT-001",
        )
        console.print(f"  Resolution: [{'green' if resolved else 'red'}]{'SUCCESS' if resolved else 'FAILED'}[/]")
        # Verify remaining queue
        remaining = qm.load_queue()
        console.print(f"  Remaining open cases: {len(remaining)}")
    else:
        console.print("  [dim]No open cases in queue (all resolved or no escalations)[/dim]")

    # ── 3. Supervisor Dashboard ───────────────────────────────────────────────
    console.print("\n[bold]Step 3: Supervisor Dashboard[/bold]")
    dashboard = SupervisorDashboard()
    dashboard.render()

    console.print(f"\n[bold green]✅ Layer 5 complete![/bold green]")
    console.print(f"   Escalations managed : {stats.total_open}")
    console.print(f"   Agents available    : {stats.available_agents}")
    console.print(f"   Dashboard rendered  : ✓")


if __name__ == "__main__":
    run_layer5()
