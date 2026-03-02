"""
agents/layer1_strategic/orchestrator.py
────────────────────────────────────────
Layer 1 Orchestrator — LangGraph state machine

Wires together the four Layer 1 agents:
  1. SegmentationAgent   → CustomerSegment + tone + strategy
  2. PropensityAgent     → lapse_score + intervention_intensity
  3. TimingAgent         → best_contact_window + best_days
  4. ChannelSelectorAgent→ channel_sequence

Then builds a RenewalJourney (with steps) and persists it to SQLite.

State machine nodes:
  START → segment → propensity → timing → channel → build_journey → END

Uses gemini-3.1-pro-preview as the orchestrator model for the journey
builder step (assembling the final plan).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import TypedDict, Optional, Any

from loguru import logger
from langgraph.graph import StateGraph, END

from core.config import settings, get_gemini_client
from core.models import (
    Channel, Customer, CustomerSegment, JourneyStatus,
    JourneyStep, Policy, RenewalJourney,
)
from core.database import create_journey, get_customer, get_policy
from agents.layer1_strategic.segmentation import SegmentationAgent
from agents.layer1_strategic.propensity import PropensityAgent
from agents.layer1_strategic.timing import TimingAgent, _days_to_due
from agents.layer1_strategic.channel_selector import ChannelSelectorAgent


# ── LangGraph State schema ─────────────────────────────────────────────────────

class JourneyState(TypedDict):
    # inputs
    customer:           Customer
    policy:             Policy

    # outputs from each agent node
    segment:            Optional[str]
    recommended_tone:   Optional[str]
    recommended_strategy: Optional[str]
    risk_flag:          Optional[str]

    lapse_score:        Optional[int]
    intervention_intensity: Optional[str]
    top_reasons:        Optional[list[str]]
    recommended_actions: Optional[list[str]]

    best_contact_window: Optional[str]
    best_days:           Optional[list[str]]
    salary_day_flag:     Optional[bool]
    urgency_override:    Optional[bool]

    channel_sequence:   Optional[list[Channel]]

    # final output
    journey:            Optional[RenewalJourney]
    error:              Optional[str]


# ── Step builder ──────────────────────────────────────────────────────────────

def _build_steps(
    channel_sequence: list[Channel],
    days_to_due: int,
    intensity: str,
    strategy: str,
    tone: str,
    contact_window: str,
    best_days: list[str],
) -> list[JourneyStep]:
    """
    Builds an ordered list of JourneyStep objects.

    Timing logic (trigger_days = days before due date):
      - urgency/intensive  : start D-3 or same day
      - moderate           : start D-7
      - light              : start D-14
      - none               : start D-5

    Each channel fires one step, spaced 1-2 days apart.
    """
    INTENSITY_START = {
        "urgent":    min(days_to_due, 3),
        "intensive": min(days_to_due, 5),
        "moderate":  min(days_to_due, 7),
        "light":     min(days_to_due, 14),
        "none":      min(days_to_due, 5),
    }

    start_days_before = INTENSITY_START.get(intensity, 7)
    steps = []

    # map channel → interval (days between steps)
    CHANNEL_GAP = {
        Channel.EMAIL:    2,
        Channel.WHATSAPP: 1,
        Channel.SMS:      1,
        Channel.VOICE:    1,
        Channel.HUMAN:    0,
    }

    current_offset = start_days_before  # days before due date
    for i, ch in enumerate(channel_sequence):
        # trigger_days: negative = before due date (e.g. -7 = 7 days before)
        trigger = -current_offset  # store as negative for clarity

        steps.append(JourneyStep(
            step_number    = i + 1,
            trigger_days   = trigger,
            channel        = ch,
            strategy       = strategy,
            tone           = tone,
            scheduled_time = contact_window.split("–")[0] if "–" in contact_window else contact_window.split("-")[0],
            completed      = False,
        ))

        gap = CHANNEL_GAP.get(ch, 1)
        current_offset = max(current_offset - gap, 1)

    return steps


# ── Graph nodes ────────────────────────────────────────────────────────────────

_seg_agent  = None
_prop_agent = None
_tim_agent  = None
_ch_agent   = None


def _get_agents():
    global _seg_agent, _prop_agent, _tim_agent, _ch_agent
    if _seg_agent is None:
        _seg_agent  = SegmentationAgent()
        _prop_agent = PropensityAgent()
        _tim_agent  = TimingAgent()
        _ch_agent   = ChannelSelectorAgent()
    return _seg_agent, _prop_agent, _tim_agent, _ch_agent


def node_segment(state: JourneyState) -> dict:
    """Node 1: classify customer into a segment."""
    seg, _, _, _ = _get_agents()
    cust, pol    = state["customer"], state["policy"]
    try:
        result = seg.run(cust, pol)
        return {
            "segment":               result.segment.value,
            "recommended_tone":      result.recommended_tone,
            "recommended_strategy":  result.recommended_strategy,
            "risk_flag":             result.risk_flag,
        }
    except Exception as e:
        logger.error(f"Segmentation failed: {e}")
        return {"segment": "nudge_needed", "error": str(e)}


def node_propensity(state: JourneyState) -> dict:
    """Node 2: score lapse probability."""
    _, prop, _, _ = _get_agents()
    cust, pol     = state["customer"], state["policy"]
    try:
        result = prop.run(cust, pol, segment=state.get("segment"))
        return {
            "lapse_score":             result.lapse_score,
            "intervention_intensity":  result.intervention_intensity,
            "top_reasons":             result.top_reasons,
            "recommended_actions":     result.recommended_actions,
        }
    except Exception as e:
        logger.error(f"Propensity failed: {e}")
        return {"lapse_score": 50, "intervention_intensity": "moderate", "error": str(e)}


def node_timing(state: JourneyState) -> dict:
    """Node 3: determine best contact window."""
    _, _, tim, _ = _get_agents()
    cust, pol    = state["customer"], state["policy"]
    try:
        result = tim.run(cust, pol, intensity=state.get("intervention_intensity", "moderate"))
        return {
            "best_contact_window": result.best_contact_window,
            "best_days":           result.best_days,
            "salary_day_flag":     result.salary_day_flag,
            "urgency_override":    result.urgency_override,
        }
    except Exception as e:
        logger.error(f"Timing failed: {e}")
        return {"best_contact_window": "10:00-12:00", "best_days": ["Monday"], "error": str(e)}


def node_channel(state: JourneyState) -> dict:
    """Node 4: select ordered channel sequence."""
    _, _, _, ch = _get_agents()
    cust, pol   = state["customer"], state["policy"]
    try:
        result = ch.run(
            cust, pol,
            segment          = state.get("segment", "nudge_needed"),
            lapse_score      = state.get("lapse_score", 50),
            urgency_override = state.get("urgency_override", False),
        )
        return {"channel_sequence": result.channel_sequence}
    except Exception as e:
        logger.error(f"Channel selection failed: {e}")
        return {"channel_sequence": [Channel("whatsapp"), Channel("sms")], "error": str(e)}


def node_build_journey(state: JourneyState) -> dict:
    """Node 5: assemble RenewalJourney and persist to DB."""
    cust = state["customer"]
    pol  = state["policy"]

    days = _days_to_due(pol)
    journey_id = f"JRN-{uuid.uuid4().hex[:8].upper()}"

    channel_sequence = state.get("channel_sequence") or [Channel("whatsapp"), Channel("sms")]
    intensity        = state.get("intervention_intensity") or "moderate"
    strategy         = state.get("recommended_strategy") or "renewal_reminder"
    tone             = state.get("recommended_tone") or "friendly"
    contact_window   = state.get("best_contact_window") or "10:00-12:00"
    best_days        = state.get("best_days") or ["Monday", "Wednesday"]
    segment_str      = state.get("segment") or "nudge_needed"
    lapse_score      = state.get("lapse_score") or 50

    steps = _build_steps(
        channel_sequence = channel_sequence,
        days_to_due      = days,
        intensity        = intensity,
        strategy         = strategy,
        tone             = tone,
        contact_window   = contact_window,
        best_days        = best_days,
    )

    journey = RenewalJourney(
        journey_id       = journey_id,
        policy_number    = pol.policy_number,
        customer_id      = cust.customer_id,
        status           = JourneyStatus.NOT_STARTED,
        segment          = CustomerSegment(segment_str),
        lapse_score      = lapse_score,
        channel_sequence = channel_sequence,
        steps            = steps,
    )

    try:
        create_journey(journey)
        logger.info(
            f"Journey created {journey_id} | {pol.policy_number} | {cust.name} "
            f"| segment={segment_str} | score={lapse_score} | steps={len(steps)}"
        )
    except Exception as e:
        logger.error(f"Failed to persist journey: {e}")

    return {"journey": journey}


# ── Graph builder ──────────────────────────────────────────────────────────────

def build_layer1_graph() -> Any:
    """Compile the Layer 1 LangGraph state machine."""
    graph = StateGraph(JourneyState)

    graph.add_node("segment",       node_segment)
    graph.add_node("propensity",    node_propensity)
    graph.add_node("timing",        node_timing)
    graph.add_node("channel",       node_channel)
    graph.add_node("build_journey", node_build_journey)

    graph.set_entry_point("segment")
    graph.add_edge("segment",       "propensity")
    graph.add_edge("propensity",    "timing")
    graph.add_edge("timing",        "channel")
    graph.add_edge("channel",       "build_journey")
    graph.add_edge("build_journey", END)

    return graph.compile()


# ── Public entry point ────────────────────────────────────────────────────────

def run_layer1(customer: Customer, policy: Policy) -> RenewalJourney:
    """Run the full Layer 1 pipeline for a single customer+policy."""
    app = build_layer1_graph()
    initial_state: JourneyState = {
        "customer": customer,
        "policy":   policy,
        "segment":  None, "recommended_tone": None, "recommended_strategy": None,
        "risk_flag": None, "lapse_score": None, "intervention_intensity": None,
        "top_reasons": None, "recommended_actions": None,
        "best_contact_window": None, "best_days": None,
        "salary_day_flag": None, "urgency_override": None,
        "channel_sequence": None, "journey": None, "error": None,
    }
    final_state = app.invoke(initial_state)
    return final_state["journey"]


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from rich.console import Console
    from rich.table import Table
    from rich import box
    from core.database import get_policies_due_within_days, get_customer as db_get_customer

    console = Console()
    console.print("\n[bold cyan]Layer 1 Orchestrator — Full Pipeline Test[/bold cyan]\n")

    policies = get_policies_due_within_days(60)
    console.print(f"Processing [bold]{len(policies)}[/bold] policies through Layer 1...\n")

    results_table = Table(
        "Journey ID", "Policy", "Customer", "Segment",
        "Score", "Intensity", "Steps", "Channels",
        box=box.ROUNDED, show_lines=False,
        title="Layer 1 Journey Plans",
    )

    journeys_created = 0
    for pol in policies:
        cust = db_get_customer(pol.customer_id)
        if not cust:
            continue

        console.print(f"  → Running pipeline for [bold]{cust.name}[/bold] / {pol.policy_number}")
        journey = run_layer1(cust, pol)

        if journey:
            journeys_created += 1
            seq_str = " → ".join(c.value for c in journey.channel_sequence)
            results_table.add_row(
                journey.journey_id,
                pol.policy_number,
                cust.name,
                journey.segment.value if journey.segment else "—",
                str(journey.lapse_score),
                "",   # intensity not stored in journey model directly
                str(len(journey.steps)),
                seq_str,
            )

    console.print()
    console.print(results_table)

    # Show step details for top 3 riskiest
    console.print("\n[bold]Journey step plans — top 3 riskiest:[/bold]")
    # sort by lapse score (stored in journey)
    risky = [(j.lapse_score or 0, j) for j in [
        run_layer1(db_get_customer(p.customer_id), p)   # type: ignore
        for p in get_policies_due_within_days(5)
        if db_get_customer(p.customer_id)
    ]]
    risky.sort(key=lambda x: x[0], reverse=True)

    for score, j in risky[:3]:
        cust = db_get_customer(j.customer_id)
        console.print(f"\n  [bold red]{j.journey_id}[/] — {cust.name if cust else j.customer_id} (score={score})")
        for step in j.steps:
            trigger_label = f"D{step.trigger_days}" if step.trigger_days <= 0 else f"D+{step.trigger_days}"
            console.print(
                f"    Step {step.step_number}: [{trigger_label}] "
                f"{step.channel.value.upper()} @ {step.scheduled_time or '?'} "
                f"| strategy={step.strategy} | tone={step.tone}"
            )

    console.print(f"\n[bold green]✅ Layer 1 complete — {journeys_created} journeys created in DB.[/bold green]")
