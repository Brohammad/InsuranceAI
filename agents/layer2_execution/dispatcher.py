"""
agents/layer2_execution/dispatcher.py
───────────────────────────────────────
Layer 2 Dispatcher

Reads all active RenewalJourneys from DB, iterates through their
JourneySteps, and routes each step to the correct execution agent:

  Channel.WHATSAPP → WhatsAppAgent
  Channel.EMAIL    → EmailAgent
  Channel.VOICE    → VoiceAgent
  Channel.SMS      → WhatsAppAgent (SMS text, different channel flag)
  Channel.HUMAN    → Escalation queue (no execution agent)

After each step:
  1. Logs the Interaction to DB
  2. Checks if outcome = PAYMENT_MADE → marks journey PAYMENT_DONE + stops
  3. Checks if outcome = OPT_OUT → marks journey OPTED_OUT + stops
  4. Checks if objection triggered → runs ObjectionHandler
  5. Checks payment status via PaymentAgent.check_status()

All actual delivery is MOCKED during testing (settings.mock_delivery=True).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from loguru import logger
from rich.console import Console
from rich.table import Table
from rich import box
from rich.progress import track

from core.config import settings
from core.models import (
    Channel, Customer, Interaction, InteractionOutcome,
    JourneyStatus, Policy, RenewalJourney,
)
from core.database import (
    get_policies_due_within_days,
    get_customer,
    get_policy,
    log_interaction,
    update_journey_status,
    mark_payment_received,
    create_escalation,
    get_renewal_stats,
)
from agents.layer2_execution.whatsapp_agent   import WhatsAppAgent
from agents.layer2_execution.email_agent      import EmailAgent
from agents.layer2_execution.voice_agent      import VoiceAgent
from agents.layer2_execution.payment_agent    import PaymentAgent
from agents.layer2_execution.objection_handler import ObjectionHandlerAgent


# ── Dispatcher ────────────────────────────────────────────────────────────────

class Layer2Dispatcher:
    """Routes journey steps to the correct execution agent."""

    def __init__(self):
        self.wa_agent   = WhatsAppAgent()
        self.em_agent   = EmailAgent()
        self.vo_agent   = VoiceAgent()
        self.pay_agent  = PaymentAgent()
        self.obj_agent  = ObjectionHandlerAgent()
        logger.info("Layer2Dispatcher ready")

    def _dispatch_step(
        self,
        channel:    Channel,
        customer:   Customer,
        policy:     Policy,
        journey_id: str,
        step_num:   int,
        tone:       str,
        strategy:   str,
    ) -> tuple[InteractionOutcome, Interaction]:
        """Run the correct agent for a channel, return (outcome, interaction)."""

        if channel == Channel.WHATSAPP:
            _, interaction = self.wa_agent.run(customer, policy, journey_id, tone, strategy)

        elif channel == Channel.EMAIL:
            _, interaction = self.em_agent.run(customer, policy, journey_id, tone, strategy)

        elif channel == Channel.VOICE:
            _, interaction = self.vo_agent.run(customer, policy, journey_id, step_num, tone, strategy)

        elif channel == Channel.SMS:
            # SMS reuses WhatsApp agent but logs as SMS channel
            _, interaction = self.wa_agent.run(customer, policy, journey_id, tone, strategy)
            interaction.channel = Channel.SMS

        elif channel == Channel.HUMAN:
            # No execution — create escalation + return escalated outcome
            from core.models import EscalationCase, EscalationPriority, EscalationReason
            case = EscalationCase(
                case_id       = f"ESC-{uuid.uuid4().hex[:8].upper()}",
                journey_id    = journey_id,
                policy_number = policy.policy_number,
                customer_id   = customer.customer_id,
                reason        = EscalationReason.REQUESTED_HUMAN,
                priority      = EscalationPriority.P3_NORMAL,
                briefing_note = (
                    f"Auto-escalated: Journey {journey_id} reached HUMAN step. "
                    f"Customer: {customer.name}, Policy: {policy.policy_number}, "
                    f"Premium: ₹{policy.annual_premium:,.0f}"
                ),
            )
            create_escalation(case)

            interaction = Interaction(
                interaction_id  = f"INT-{uuid.uuid4().hex[:8].upper()}",
                journey_id      = journey_id,
                policy_number   = policy.policy_number,
                customer_id     = customer.customer_id,
                channel         = Channel.HUMAN,
                direction       = "outbound",
                message_content = f"[ESCALATED TO HUMAN] {case.briefing_note}",
                language        = customer.preferred_language,
                sent_at         = datetime.now(),
                outcome         = InteractionOutcome.ESCALATED,
            )

        else:
            # Fallback
            interaction = Interaction(
                interaction_id  = f"INT-{uuid.uuid4().hex[:8].upper()}",
                journey_id      = journey_id,
                policy_number   = policy.policy_number,
                customer_id     = customer.customer_id,
                channel         = channel,
                direction       = "outbound",
                message_content = "[UNKNOWN CHANNEL]",
                language        = customer.preferred_language,
                sent_at         = datetime.now(),
                outcome         = InteractionOutcome.NO_RESPONSE,
            )

        return interaction.outcome, interaction   # type: ignore[return-value]

    def run_journey(self, journey: RenewalJourney) -> dict:
        """Execute all steps for a single journey. Returns a summary dict."""
        cust = get_customer(journey.customer_id)
        pol  = get_policy(journey.policy_number)
        if not cust or not pol:
            logger.error(f"Missing customer/policy for journey {journey.journey_id}")
            return {"journey_id": journey.journey_id, "error": "missing data"}

        logger.info(
            f"Dispatching journey {journey.journey_id} | {cust.name} | "
            f"{len(journey.steps)} steps | segment={journey.segment}"
        )

        results = []
        payment_done = False

        for step in journey.steps:
            if payment_done:
                break

            outcome, interaction = self._dispatch_step(
                channel    = step.channel,
                customer   = cust,
                policy     = pol,
                journey_id = journey.journey_id,
                step_num   = step.step_number,
                tone       = step.tone,
                strategy   = step.strategy,
            )

            # Persist interaction
            log_interaction(interaction)

            results.append({
                "step":    step.step_number,
                "channel": step.channel.value,
                "outcome": outcome.value,
            })

            # Check payment
            if outcome == InteractionOutcome.PAYMENT_MADE:
                payment_done = True
                mark_payment_received(journey.journey_id)
                logger.info(f"PAYMENT RECEIVED — stopping journey {journey.journey_id}")
                break

            # Check opt-out
            if outcome == InteractionOutcome.OPT_OUT:
                update_journey_status(journey.journey_id, JourneyStatus.OPTED_OUT)
                logger.info(f"OPT-OUT — stopping journey {journey.journey_id}")
                break

            # If objection detected on voice/whatsapp, run objection handler
            if outcome == InteractionOutcome.OBJECTION:
                obj_result = self.obj_agent.run(cust, pol, journey.journey_id)
                logger.info(
                    f"Objection '{obj_result.objection_type.value}' handled | "
                    f"escalate={obj_result.should_escalate}"
                )
                if obj_result.should_escalate and obj_result.escalation_case:
                    create_escalation(obj_result.escalation_case)
                    update_journey_status(journey.journey_id, JourneyStatus.ESCALATED)
                    break

        # Check payment gateway status (mock: 30% chance)
        if not payment_done and journey.steps:
            link = self.pay_agent.create_link(cust, pol)
            status = self.pay_agent.check_status(link.txn_id)
            if status.status == "paid":
                payment_done = True
                mark_payment_received(journey.journey_id)
                logger.info(
                    f"Payment confirmed via gateway check | "
                    f"journey={journey.journey_id} | method={status.payment_method}"
                )

        if not payment_done:
            update_journey_status(journey.journey_id, JourneyStatus.IN_PROGRESS)

        return {
            "journey_id":     journey.journey_id,
            "customer":       cust.name,
            "policy":         pol.policy_number,
            "segment":        journey.segment.value if journey.segment else "—",
            "lapse_score":    journey.lapse_score,
            "steps_executed": len(results),
            "outcomes":       results,
            "payment_done":   payment_done,
        }

    def run_all(self, journeys: list[RenewalJourney]) -> list[dict]:
        """Run all journeys. Returns list of summary dicts."""
        summaries = []
        for journey in track(journeys, description="Dispatching journeys..."):
            summary = self.run_journey(journey)
            summaries.append(summary)
        return summaries


# ── DB helper: load journeys ──────────────────────────────────────────────────

def load_active_journeys() -> list[RenewalJourney]:
    """Load all NOT_STARTED journeys from DB (deduplicated by policy)."""
    import sqlite3, json
    from core.config import settings as cfg
    from core.models import (
        CustomerSegment, JourneyStep, JourneyStatus, EscalationReason,
    )

    conn = sqlite3.connect(str(cfg.abs_db_path))
    conn.row_factory = sqlite3.Row

    # Deduplicate: keep latest journey per policy
    rows = conn.execute("""
        SELECT j.*
        FROM renewal_journeys j
        INNER JOIN (
            SELECT policy_number, MAX(created_at) AS latest
            FROM renewal_journeys
            GROUP BY policy_number
        ) latest_j ON j.policy_number = latest_j.policy_number
                     AND j.created_at = latest_j.latest
        WHERE j.status = 'not_started'
        ORDER BY j.created_at DESC
    """).fetchall()
    conn.close()

    journeys = []
    for row in rows:
        channel_seq  = [Channel(c) for c in json.loads(row["channel_sequence"])]
        raw_steps    = json.loads(row["steps"])
        steps        = []
        for s in raw_steps:
            steps.append(JourneyStep(
                step_number    = s["step_number"],
                trigger_days   = s["trigger_days"],
                channel        = Channel(s["channel"]),
                strategy       = s["strategy"],
                tone           = s["tone"],
                scheduled_time = s.get("scheduled_time"),
                completed      = s.get("completed", False),
            ))

        journeys.append(RenewalJourney(
            journey_id       = row["journey_id"],
            policy_number    = row["policy_number"],
            customer_id      = row["customer_id"],
            status           = JourneyStatus(row["status"]),
            segment          = CustomerSegment(row["segment"]) if row["segment"] else None,
            lapse_score      = row["lapse_score"],
            channel_sequence = channel_seq,
            steps            = steps,
        ))
    return journeys


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    console = Console()
    console.print("\n[bold cyan]Layer 2 Dispatcher — Full Execution Test[/bold cyan]\n")

    journeys = load_active_journeys()
    console.print(f"Found [bold]{len(journeys)}[/bold] active journeys to dispatch\n")

    dispatcher = Layer2Dispatcher()
    summaries  = dispatcher.run_all(journeys)

    # Results table
    table = Table(
        "Journey ID", "Customer", "Policy", "Segment",
        "Score", "Steps", "Paid?", "Outcomes",
        box=box.ROUNDED, show_lines=False,
        title="Layer 2 Execution Results",
    )

    PAID_STYLE = "[bold green]YES ✅[/]"
    NOPAY_STYLE = "[dim]no[/]"

    for s in summaries:
        outcomes_str = " | ".join(
            f"{r['channel'][:2].upper()}:{r['outcome'][:4]}"
            for r in s.get("outcomes", [])
        )
        table.add_row(
            s.get("journey_id", "?")[:12],
            s.get("customer", "?"),
            s.get("policy", "?"),
            s.get("segment", "?"),
            str(s.get("lapse_score", "?")),
            str(s.get("steps_executed", 0)),
            PAID_STYLE if s.get("payment_done") else NOPAY_STYLE,
            outcomes_str,
        )

    console.print(table)

    # Stats from DB
    stats = get_renewal_stats()
    console.print("\n[bold]DB Stats after Layer 2:[/bold]")
    for k, v in stats.items():
        console.print(f"  {k:<30} {v}")

    paid_count = sum(1 for s in summaries if s.get("payment_done"))
    console.print(
        f"\n[bold green]✅ Layer 2 complete — "
        f"{paid_count}/{len(summaries)} journeys resulted in payment.[/bold green]"
    )
