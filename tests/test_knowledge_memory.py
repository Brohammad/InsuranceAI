"""
tests/test_knowledge_memory.py
────────────────────────────────
Tests for:
  1. RAG Knowledge Base  — build, semantic query, objection lookup, context builder
  2. Customer Memory Store — seed, update, get_context, get_summary
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()


def test_rag_knowledge_base():
    console.rule("[bold cyan]1. RAG Knowledge Base[/bold cyan]")

    from knowledge.rag_knowledge_base import RagKnowledgeBase, ALL_DOCUMENTS

    kb = RagKnowledgeBase()

    # Build / index
    console.print("[bold]Building index...[/bold]")
    n = kb.build()
    stats = kb.stats()

    console.print(f"  Backend  : [cyan]{stats['backend']}[/cyan]")
    console.print(f"  Indexed  : [green]{stats['indexed']}[/green] / {stats['total_documents']} total docs")
    console.print(f"  By category:")
    for cat, count in stats["by_category"].items():
        console.print(f"    {cat:<15} {count} docs")

    assert stats["indexed"] > 0, "No documents indexed"
    assert stats["total_documents"] >= 38, f"Expected ≥38 docs, got {stats['total_documents']}"

    # Semantic queries
    queries = [
        ("what happens if I miss a premium", "faq"),
        ("premium is too high I can't afford", "objection"),
        ("how is maturity benefit calculated", "calculator"),
        ("IRDAI complaint grievance process", "compliance"),
        ("how to open a call with customer", "script"),
    ]

    console.print("\n[bold]Semantic search results:[/bold]")
    t = Table("Query", "Top Match", "Category", "Score", box=box.SIMPLE)
    for query, expected_cat in queries:
        results = kb.query(query, n=1)
        assert results, f"No results for: {query}"
        top = results[0]
        t.add_row(
            query[:40],
            top["title"][:45],
            top["category"],
            f"{top['score']:.3f}",
        )
    console.print(t)

    # Objection response lookup
    console.print("\n[bold]Objection response lookup:[/bold]")
    objections = [
        "my premium is very expensive",
        "I'll renew next month no rush",
        "LIC is more trustworthy",
        "I want to surrender my policy",
        "the company will reject my claim",
    ]
    for obj in objections:
        result = kb.get_objection_response(obj)
        status = "[green]✓[/]" if result else "[yellow]no match[/]"
        title  = result["title"] if result else "—"
        console.print(f"  {status} '{obj[:40]}' → {title}")

    # Context builder
    console.print("\n[bold]Context builder for agent prompt:[/bold]")
    ctx = kb.build_context("customer says premium too high can't afford", n=2)
    console.print(Panel(ctx[:400] + "...", title="Built Context", border_style="dim"))
    assert len(ctx) > 50, "Context too short"

    console.print("\n[bold green]✅ RAG Knowledge Base: PASSED[/bold green]")


def test_customer_memory():
    console.rule("[bold cyan]2. Customer Memory Store[/bold cyan]")

    from memory.customer_memory import CustomerMemoryStore

    mem = CustomerMemoryStore()

    # Seed from customers
    console.print("[bold]Seeding from customers table...[/bold]")
    created = mem.seed_from_customers()
    stats   = mem.stats()
    console.print(f"  Created: {created} new records")
    console.print(f"  Total tracked: {stats['total_customers_tracked']}")

    assert stats["total_customers_tracked"] >= 20, "Expected at least 20 customers"

    # Pick a customer to test with
    import sqlite3
    from core.config import settings
    conn = sqlite3.connect(str(settings.abs_db_path))
    conn.row_factory = sqlite3.Row
    cust = conn.execute("SELECT customer_id, name FROM customers LIMIT 1").fetchone()
    conn.close()
    cid  = cust["customer_id"]
    name = cust["name"]

    # Reset this customer's memory to a clean state for deterministic test
    import sqlite3 as _sql
    _conn = _sql.connect(str(settings.abs_db_path))
    _conn.execute("DELETE FROM customer_memory WHERE customer_id=?", (cid,))
    _conn.commit()
    _conn.close()
    mem.seed_from_customers()   # re-seed the deleted row

    # Simulate interactions
    console.print(f"\n[bold]Simulating interactions for {name} ({cid}):[/bold]")
    interactions = [
        dict(channel="whatsapp", outcome="delivered",   sentiment=0.1,  objection=""),
        dict(channel="email",    outcome="read",        sentiment=0.3,  objection=""),
        dict(channel="voice",    outcome="responded",   sentiment=0.5,  objection="premium too high"),
        dict(channel="whatsapp", outcome="payment_made",sentiment=0.8,  objection="", payment_received=True),
    ]
    for i, iact in enumerate(interactions):
        mem.update(cid, interaction_id=f"TEST-{i:03d}", **iact)
        console.print(f"  [{i+1}] {iact['channel']:<12} → {iact['outcome']}")

    # Get context
    ctx = mem.get_context(cid)
    assert ctx is not None,          "Context should not be None"
    assert ctx.total_interactions == 4
    assert "premium too high" in ctx.objections_raised
    assert ctx.successful_channel in ("email", "voice", "whatsapp")  # first positive outcome
    assert len(ctx.recent_interactions) == 4

    console.print(f"\n[bold]Context for {name}:[/bold]")
    t = Table("Field", "Value", box=box.SIMPLE)
    t.add_row("Total interactions",  str(ctx.total_interactions))
    t.add_row("Avg sentiment",       f"{ctx.avg_sentiment:+.3f}")
    t.add_row("Objections raised",   ", ".join(ctx.objections_raised))
    t.add_row("Channels tried",      ", ".join(ctx.channels_tried))
    t.add_row("Successful channel",  ctx.successful_channel)
    t.add_row("Last outcome",        ctx.last_outcome)
    console.print(t)

    # Summary for agent prompt
    summary = mem.get_summary(cid)
    console.print(Panel(summary, title="[bold]Agent Prompt Summary[/bold]", border_style="cyan"))
    assert len(summary) > 20, "Summary too short"

    # Stats after updates
    stats2 = mem.stats()
    console.print(f"\n  Customers with interactions: {stats2['with_interactions']}")
    console.print(f"  Avg sentiment across all   : {stats2['avg_sentiment']:+.3f}")

    console.print("\n[bold green]✅ Customer Memory Store: PASSED[/bold green]")


if __name__ == "__main__":
    console.print("\n[bold cyan]Knowledge Layer + Memory Store — Test Run[/bold cyan]\n")
    test_rag_knowledge_base()
    test_customer_memory()
    console.print("\n[bold green]═══ All knowledge/memory tests passed ═══[/bold green]\n")
