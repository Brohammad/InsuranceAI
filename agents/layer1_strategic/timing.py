"""
agents/layer1_strategic/timing.py
───────────────────────────────────
Timing Agent — Layer 1

Determines the OPTIMAL contact window for each customer, respecting:
  • TRAI DND regulations (9 AM – 9 PM only)
  • Customer preferred_call_time from CRM
  • Salary day heuristic (credit hits on 1st & 7th of month)
  • Urgency override — if due in ≤ 5 days, contact next business morning
  • Weekend preference — many salaried customers more reachable Saturday
  • Occupation-based heuristic (farmers → evening, office → lunch/evening)

Output:
  TimingResult
    best_contact_window : str          e.g. "10:00–12:00"
    best_days           : list[str]    e.g. ["Monday", "Wednesday"]
    avoid_days          : list[str]    e.g. ["Sunday"]
    salary_day_flag     : bool         True if 1st/7th of month is within 7 days
    urgency_override    : bool         True if due date ≤ 5 days
    rationale           : str

Uses gemini-2.5-flash.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta

from loguru import logger

from core.config import settings, get_gemini_client
from core.models import Customer, Policy


# ── Output model ──────────────────────────────────────────────────────────────

@dataclass
class TimingResult:
    best_contact_window : str
    best_days           : list[str] = field(default_factory=list)
    avoid_days          : list[str] = field(default_factory=list)
    salary_day_flag     : bool      = False
    urgency_override    : bool      = False
    rationale           : str       = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _days_to_due(policy: Policy) -> int:
    return max((policy.renewal_due_date - date.today()).days, 0)


def _next_salary_days() -> list[str]:
    """Returns the next occurrences of 1st and 7th within 30 days."""
    today = date.today()
    results = []
    for target_day in (1, 7):
        # this month
        try:
            d = today.replace(day=target_day)
        except ValueError:
            d = today  # fallback
        if d < today:
            # push to next month
            if today.month == 12:
                d = date(today.year + 1, 1, target_day)
            else:
                d = date(today.year, today.month + 1, target_day)
        results.append(d.strftime("%A %d %b"))
    return results


# ── Prompt template ───────────────────────────────────────────────────────────

TIMING_PROMPT = """
You are a communication-timing specialist at Suraksha Life Insurance.

Given the customer profile below, recommend the OPTIMAL contact windows
for an insurance renewal follow-up campaign.

HARD RULES:
1. TRAI regulations: calls/WhatsApp only 9:00 AM – 9:00 PM IST
2. Do NOT schedule on national holidays
3. If urgency_override is true (due ≤ 5 days), recommend contacting on the
   very NEXT business day morning (9:00–11:00)
4. Salary day bonus: if the 1st or 7th of the month falls within 7 days,
   flag salary_day_flag=true and prefer that day (customers have cash)

CUSTOMER PROFILE:
Name:                 {name}
Age:                  {age}
Occupation:           {occupation}
Preferred Language:   {language}
Preferred Call Time:  {preferred_call_time}
Preferred Channel:    {channel}
On DND:               {dnd}

POLICY CONTEXT:
Product Type:         {product_type}
Annual Premium:       ₹{premium:,}
Renewal Due In:       {days_to_due} days
Urgency Override:     {urgency_override}
Intervention Level:   {intensity}
Upcoming Salary Days: {salary_days}

OCCUPATION HEURISTICS:
- farmer / agricultural → contact 6–8 PM (after field work)
- daily_wage / labour   → contact 8–9 AM or 7–8 PM
- office / corporate    → contact 12–1 PM (lunch) or 6–8 PM
- homemaker             → contact 10 AM–12 PM or 3–5 PM
- self_employed / business → contact 10 AM–12 PM or 7–8 PM
- retired               → contact 9–11 AM or 4–6 PM
- student               → contact 5–8 PM

Respond with ONLY a JSON object — no markdown, no explanation:
{{
  "best_contact_window": "<HH:MM–HH:MM>",
  "best_days": ["<day1>", "<day2>"],
  "avoid_days": ["<day>"],
  "salary_day_flag": <true|false>,
  "urgency_override": <true|false>,
  "rationale": "<1-2 sentence explanation>"
}}
"""


# ── Agent class ────────────────────────────────────────────────────────────────

class TimingAgent:
    """Recommends optimal contact windows per customer."""

    def __init__(self):
        self.client = get_gemini_client()
        self.model  = settings.model_classify   # gemini-2.5-flash
        logger.info(f"TimingAgent initialised | model={self.model}")

    def run(
        self,
        customer: Customer,
        policy: Policy,
        intensity: str = "moderate",
    ) -> TimingResult:
        logger.debug(f"Timing for {policy.policy_number} | {customer.name}")

        days     = _days_to_due(policy)
        urgency  = days <= 5
        sal_days = _next_salary_days()

        prompt = TIMING_PROMPT.format(
            name               = customer.name,
            age                = customer.age,
            occupation         = customer.occupation,
            language           = customer.preferred_language.value,
            preferred_call_time= customer.preferred_call_time,
            channel            = customer.preferred_channel.value,
            dnd                = customer.is_on_dnd,
            product_type       = policy.product_type.value,
            premium            = policy.annual_premium,
            days_to_due        = days,
            urgency_override   = urgency,
            intensity          = intensity,
            salary_days        = ", ".join(sal_days),
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

        result = TimingResult(
            best_contact_window = data["best_contact_window"],
            best_days           = data.get("best_days", []),
            avoid_days          = data.get("avoid_days", []),
            salary_day_flag     = bool(data.get("salary_day_flag", False)),
            urgency_override    = bool(data.get("urgency_override", urgency)),
            rationale           = data.get("rationale", ""),
        )

        logger.info(
            f"Timing {policy.policy_number} | {customer.name} "
            f"→ {result.best_contact_window} on {result.best_days} "
            f"| urgency={result.urgency_override}"
        )
        return result


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from rich.console import Console
    from rich.table import Table
    from rich import box

    from core.database import get_policies_due_within_days, get_customer

    console = Console()
    agent   = TimingAgent()

    policies = get_policies_due_within_days(60)
    console.print(f"\nCalculating contact timing for [bold]{len(policies)}[/bold] policies...\n")

    table = Table(
        "Policy", "Customer", "Occupation", "Due In",
        "Window", "Best Days", "Urgency", "Salary Day",
        box=box.ROUNDED, show_lines=False,
        title="Contact Timing Recommendations",
    )

    for pol in policies:
        cust = get_customer(pol.customer_id)
        if not cust:
            continue

        days = _days_to_due(pol)
        result = agent.run(cust, pol)

        urgency_str = "[bold red]YES[/]" if result.urgency_override else "no"
        salary_str  = "[green]YES[/]" if result.salary_day_flag else "no"

        table.add_row(
            pol.policy_number,
            cust.name,
            cust.occupation[:12],
            f"{days}d",
            result.best_contact_window,
            ", ".join(result.best_days[:2]),
            urgency_str,
            salary_str,
        )

    console.print(table)

    # Detail view for urgent cases
    console.print("\n[bold]Urgent cases — full rationale:[/bold]")
    for pol in get_policies_due_within_days(5):
        cust = get_customer(pol.customer_id)
        if not cust:
            continue
        r = agent.run(cust, pol)
        console.print(f"\n  [bold red]{pol.policy_number}[/] — {cust.name} ({_days_to_due(pol)}d left)")
        console.print(f"  Window : {r.best_contact_window}  |  Days: {', '.join(r.best_days)}")
        console.print(f"  Avoid  : {', '.join(r.avoid_days) or 'none'}")
        console.print(f"  Rationale: {r.rationale}")

    console.print("\n[bold green]✅ Timing analysis complete.[/bold green]")
