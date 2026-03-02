"""
agents/layer1_strategic/propensity.py
──────────────────────────────────────
Propensity Agent — Layer 1

Scores each (customer, policy) pair with a lapse probability: 0–100.
  0  = virtually certain to renew
  100 = virtually certain to lapse

Also outputs:
  - top_reasons        : list[str] — driving factors behind the score
  - intervention_intensity : "none" | "light" | "moderate" | "intensive" | "urgent"
  - recommended_actions    : list[str] — concrete next steps for later agents

Uses gemini-2.5-flash (fast classification / scoring task).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from core.config import settings, get_gemini_client
from core.models import Customer, Policy, CustomerSegment


# ── Output model ──────────────────────────────────────────────────────────────

@dataclass
class PropensityResult:
    lapse_score: int                        # 0–100
    intervention_intensity: str            # none | light | moderate | intensive | urgent
    top_reasons: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    reasoning: str = ""


# ── Prompt template ───────────────────────────────────────────────────────────

PROPENSITY_PROMPT = """
You are a lapse-prediction specialist at Suraksha Life Insurance.

Given the customer and policy data below, output a JSON object estimating
the probability that this customer will NOT renew (i.e., let the policy lapse).

SCORING GUIDE:
- 0–20  : Very likely to renew (auto-debit, great payment history, engaged)
- 21–40 : Probably will renew but worth a gentle nudge
- 41–60 : 50/50 — needs moderate outreach
- 61–80 : At risk — missed payments, high premium burden, low engagement
- 81–100 : High risk of lapse — multiple misses, very close to due date, distress signals

INTERVENTION INTENSITY:
- none      : score 0–15, just send reminder
- light     : score 16–30, 1–2 personalised touches
- moderate  : score 31–55, multi-channel 5-day campaign
- intensive : score 56–80, daily outreach, advisor call
- urgent    : score 81–100, same-day escalation to human advisor

CUSTOMER DATA:
Name:               {name}
Age:                {age}
Occupation:         {occupation}
Preferred Language: {language}
Preferred Channel:  {channel}
On DND:             {dnd}

POLICY DATA:
Policy Number:      {policy_number}
Product Type:       {product_type}
Annual Premium:     ₹{premium:,}
Sum Assured:        ₹{sum_assured:,}
Tenure:             {tenure} years  ({years_completed} completed)
Renewal Due In:     {days_to_due} days
Has Auto-Debit:     {auto_debit}
Payment History:    {payment_history}
  → Missed:  {missed_count}  |  Late: {late_count}  |  On-Time: {ontime_count}

SEGMENT (from Segmentation Agent): {segment}

RULES:
1. auto-debit + all on_time  → score ≤ 20
2. 2+ missed + due ≤ 7 days  → score ≥ 80
3. all missed                → score ≥ 75
4. premium ≥ ₹75,000 + good history → score ≤ 30
5. single missed, rest on_time → score 35–55
6. mostly late, no auto-debit → score 50–65

Respond with ONLY a JSON object — no markdown, no explanation:
{{
  "lapse_score": <integer 0-100>,
  "intervention_intensity": "<none|light|moderate|intensive|urgent>",
  "top_reasons": ["<reason1>", "<reason2>", "<reason3>"],
  "recommended_actions": ["<action1>", "<action2>"],
  "reasoning": "<2-3 sentence rationale>"
}}
"""


# ── Agent class ────────────────────────────────────────────────────────────────

class PropensityAgent:
    """Scores lapse probability for a (customer, policy) pair."""

    def __init__(self):
        self.client = get_gemini_client()
        self.model  = settings.model_classify   # gemini-2.5-flash
        logger.info(f"PropensityAgent initialised | model={self.model}")

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _payment_breakdown(history: list[str]) -> dict:
        return {
            "missed":  history.count("missed"),
            "late":    history.count("late"),
            "on_time": history.count("on_time"),
        }

    @staticmethod
    def _days_to_due(policy: Policy) -> int:
        from datetime import date
        delta = policy.renewal_due_date - date.today()
        return max(delta.days, 0)

    # ── main entry point ─────────────────────────────────────────────────────

    def run(
        self,
        customer: Customer,
        policy: Policy,
        segment: Optional[str] = None,
    ) -> PropensityResult:
        logger.debug(f"Scoring propensity for {policy.policy_number} | {customer.name}")

        bd = self._payment_breakdown(policy.payment_history)
        days = self._days_to_due(policy)

        prompt = PROPENSITY_PROMPT.format(
            name           = customer.name,
            age            = customer.age,
            occupation     = customer.occupation,
            language       = customer.preferred_language.value,
            channel        = customer.preferred_channel.value,
            dnd            = customer.is_on_dnd,
            policy_number  = policy.policy_number,
            product_type   = policy.product_type.value,
            premium        = policy.annual_premium,
            sum_assured    = policy.sum_assured,
            tenure         = policy.tenure_years,
            years_completed= policy.years_completed,
            days_to_due    = days,
            auto_debit     = policy.has_auto_debit,
            payment_history= ", ".join(policy.payment_history),
            missed_count   = bd["missed"],
            late_count     = bd["late"],
            ontime_count   = bd["on_time"],
            segment        = segment or "unknown",
        )

        response = self.client.models.generate_content(
            model    = self.model,
            contents = prompt,
        )

        raw = response.text.strip()
        # strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)

        result = PropensityResult(
            lapse_score            = int(data["lapse_score"]),
            intervention_intensity = data["intervention_intensity"],
            top_reasons            = data.get("top_reasons", []),
            recommended_actions    = data.get("recommended_actions", []),
            reasoning              = data.get("reasoning", ""),
        )

        logger.info(
            f"Propensity scored {policy.policy_number} | {customer.name} "
            f"→ score={result.lapse_score} | intensity={result.intervention_intensity}"
        )
        return result


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from datetime import date, timedelta
    from rich.console import Console
    from rich.table import Table
    from rich import box

    from core.database import get_policies_due_within_days, get_customer

    console = Console()
    agent   = PropensityAgent()

    policies = get_policies_due_within_days(60)

    console.print(f"\nScoring propensity for [bold]{len(policies)}[/bold] policies...\n")

    table = Table(
        "Policy", "Customer", "Prod", "Premium", "Due In",
        "Missed", "Score", "Intensity",
        box=box.ROUNDED, show_lines=False,
        title="Propensity Scores",
    )

    # colour map for intensity
    INTENSITY_COLOUR = {
        "none":      "green",
        "light":     "cyan",
        "moderate":  "yellow",
        "intensive": "red",
        "urgent":    "bold red",
    }

    scored = []
    for pol in policies:
        cust = get_customer(pol.customer_id)
        if not cust:
            continue

        result = agent.run(cust, pol)

        missed = pol.payment_history.count("missed")
        days   = (pol.renewal_due_date - date.today()).days
        colour = INTENSITY_COLOUR.get(result.intervention_intensity, "white")

        table.add_row(
            pol.policy_number,
            cust.name,
            pol.product_type.value[:5],
            f"₹{pol.annual_premium:,}",
            f"{days}d",
            str(missed),
            f"[{colour}]{result.lapse_score}[/{colour}]",
            f"[{colour}]{result.intervention_intensity}[/{colour}]",
        )
        scored.append((result.lapse_score, cust.name, pol.policy_number, result.top_reasons, result.recommended_actions))

    console.print(table)

    # print top reasons for top-5 riskiest
    console.print("\n[bold]Top-5 riskiest policies — reasons:[/bold]")
    scored.sort(reverse=True)

    scored.sort(reverse=True)
    for score, name, pnum, reasons, actions in scored[:5]:
        console.print(f"\n  [bold red]{pnum}[/] — {name} (score={score})")
        for reason in reasons:
            console.print(f"    • {reason}")
        console.print(f"  [dim]Actions:[/dim]")
        for action in actions:
            console.print(f"    → {action}")

    console.print("\n[bold green]✅ Propensity scoring complete.[/bold green]")
