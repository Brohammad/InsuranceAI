"""
agents/layer1_strategic/channel_selector.py
────────────────────────────────────────────
Channel Selector Agent — Layer 1

Determines the ORDERED sequence of communication channels to use for each
customer's renewal campaign.

Channel pool: whatsapp | sms | email | voice | ivr

Rules encoded in the prompt:
  - DND customers  → SMS only (TRAI compliant)
  - WhatsApp pref + age < 60 → WhatsApp first
  - High-risk / distress   → Voice call first (human touch)
  - Wealth builder / HNI   → Email + WhatsApp (professional tone)
  - Auto-renewer           → Just WhatsApp/SMS reminder (no spam)
  - No smartphone signals  → Voice + SMS (no WhatsApp/Email)
  - Urgency override       → Voice immediately, then WhatsApp

Output:
  ChannelResult
    primary_channel  : Channel
    channel_sequence : list[Channel]   (ordered, max 4)
    rationale        : str
    dnd_restricted   : bool

Uses gemini-2.5-flash.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from loguru import logger

from core.config import settings, get_gemini_client
from core.models import Channel, Customer, Policy
from prompts.layer1 import CHANNEL_PROMPT


# ── Output model ──────────────────────────────────────────────────────────────

@dataclass
class ChannelResult:
    primary_channel  : Channel
    channel_sequence : list[Channel] = field(default_factory=list)
    rationale        : str           = ""
    dnd_restricted   : bool          = False


# ── Agent class ────────────────────────────────────────────────────────────────

class ChannelSelectorAgent:
    """Picks the optimal ordered channel sequence for a customer."""

    def __init__(self):
        self.client = get_gemini_client()
        self.model  = settings.model_classify   # gemini-2.5-flash
        logger.info(f"ChannelSelectorAgent initialised | model={self.model}")

    def run(
        self,
        customer: Customer,
        policy: Policy,
        segment: str = "nudge_needed",
        lapse_score: int = 50,
        urgency_override: bool = False,
    ) -> ChannelResult:
        logger.debug(f"Channel selection for {policy.policy_number} | {customer.name}")

        from datetime import date
        days = max((policy.renewal_due_date - date.today()).days, 0)

        prompt = CHANNEL_PROMPT.format(
            name             = customer.name,
            age              = customer.age,
            occupation       = customer.occupation,
            preferred_channel= customer.preferred_channel.value,
            language         = customer.preferred_language.value,
            dnd              = customer.is_on_dnd,
            has_whatsapp     = bool(customer.whatsapp_number),
            product_type     = policy.product_type.value,
            premium          = policy.annual_premium,
            days_to_due      = days,
            urgency_override = urgency_override,
            segment          = segment,
            lapse_score      = lapse_score,
        )

        response = self.client.models.generate_content(
            model    = self.model,
            contents = prompt,
        )

        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)

        # Parse channel strings → Channel enum
        def _parse(ch: str) -> Channel:
            try:
                return Channel(ch.lower())
            except ValueError:
                return Channel("sms")  # safe fallback

        seq = [_parse(c) for c in data.get("channel_sequence", [])]
        primary = _parse(data.get("primary_channel", seq[0].value if seq else "sms"))

        result = ChannelResult(
            primary_channel  = primary,
            channel_sequence = seq,
            rationale        = data.get("rationale", ""),
            dnd_restricted   = bool(data.get("dnd_restricted", customer.is_on_dnd)),
        )

        logger.info(
            f"Channel {policy.policy_number} | {customer.name} "
            f"→ {[c.value for c in result.channel_sequence]} "
            f"| dnd={result.dnd_restricted}"
        )
        return result


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from datetime import date
    from rich.console import Console
    from rich.table import Table
    from rich import box

    from core.database import get_policies_due_within_days, get_customer

    console = Console()
    agent   = ChannelSelectorAgent()

    policies = get_policies_due_within_days(60)
    console.print(f"\nSelecting channels for [bold]{len(policies)}[/bold] policies...\n")

    table = Table(
        "Policy", "Customer", "Age", "Pref Channel",
        "DND", "Segment", "Due In", "Sequence",
        box=box.ROUNDED, show_lines=False,
        title="Channel Selection Results",
    )

    # Simulate running segmentation + propensity inline for context
    # (in production these come from prior agents)
    from agents.layer1_strategic.segmentation import SegmentationAgent
    from agents.layer1_strategic.propensity import PropensityAgent

    seg_agent  = SegmentationAgent()
    prop_agent = PropensityAgent()

    for pol in policies:
        cust = get_customer(pol.customer_id)
        if not cust:
            continue

        days = max((pol.renewal_due_date - date.today()).days, 0)

        seg_result  = seg_agent.run(cust, pol)
        prop_result = prop_agent.run(cust, pol, segment=seg_result.segment.value)

        ch_result = agent.run(
            cust, pol,
            segment          = seg_result.segment.value,
            lapse_score      = prop_result.lapse_score,
            urgency_override = days <= 5,
        )

        dnd_str = "[red]YES[/]" if cust.is_on_dnd else "no"
        seq_str = " → ".join(c.value for c in ch_result.channel_sequence)

        table.add_row(
            pol.policy_number,
            cust.name,
            str(cust.age),
            cust.preferred_channel.value,
            dnd_str,
            seg_result.segment.value,
            f"{days}d",
            seq_str,
        )

    console.print(table)
    console.print("\n[bold green]✅ Channel selection complete.[/bold green]")
