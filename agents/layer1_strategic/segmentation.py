"""
agents/layer1_strategic/segmentation.py
────────────────────────────────────────
Segmentation Agent — Layer 1

Reads a customer + policy from the DB and classifies them into one of
six segments from chatpwc.txt:
  auto_renewer | wealth_builder | nudge_needed |
  price_sensitive | high_risk | distress

Also outputs: recommended tone, message strategy, and risk flag.
Uses gemini-2.5-flash (fast classification task).
"""

from __future__ import annotations

import json
from loguru import logger

from core.config import settings, get_gemini_client
from core.models import (
    Channel,
    Customer,
    CustomerSegment,
    Language,
    Policy,
    ProductType,
    SegmentationResult,
)


# ── Prompt template ───────────────────────────────────────────────────────────

SEGMENTATION_PROMPT = """
You are a customer segmentation expert for Suraksha Life Insurance.

Analyse the customer and policy data below and classify the customer into
exactly ONE of these segments:

SEGMENTS:
- auto_renewer     : Has auto-debit, always pays on time, minimal intervention needed
- wealth_builder   : HNI / high-value policy (premium > ₹75,000), financially comfortable
- nudge_needed     : Has paid before but sometimes late, forgets rather than refuses
- price_sensitive  : Premium feels high, has been late/missed, may think of surrendering
- high_risk        : Multiple missed payments, low engagement, likely to lapse
- distress         : Financial hardship signals, bereavement, health crisis, job loss

CUSTOMER DATA:
Name:               {name}
Age:                {age}
Occupation:         {occupation}
City / State:       {city}, {state}
Preferred Channel:  {preferred_channel}
Preferred Language: {preferred_language}
Preferred Time:     {preferred_call_time}

POLICY DATA:
Policy Number:      {policy_number}
Product Type:       {product_type}
Product Name:       {product_name}
Annual Premium:     ₹{annual_premium:,.0f}
Sum Assured:        ₹{sum_assured:,.0f}
Years Completed:    {years_completed} of {tenure_years}
Due In:             {days_until_due} days
Payment History:    {payment_history}
Has Auto-Debit:     {has_auto_debit}

RULES:
- If has_auto_debit=True AND all payments on_time → always auto_renewer
- If annual_premium >= 75000 AND payment history mostly on_time → wealth_builder
- If 2+ missed payments in history → high_risk
- If all payments missed AND occupation suggests financial stress → distress
- If payments are mix of on_time and late → nudge_needed or price_sensitive
  (price_sensitive if premium > ₹20,000 relative to occupation)

Respond with ONLY valid JSON (no markdown, no explanation):
{{
  "segment": "<one of the six segment keys>",
  "recommended_tone": "<friendly|formal|urgent|empathetic|concierge>",
  "recommended_strategy": "<e.g. tax_benefit_reminder|fund_performance|family_protection|emi_offer|premium_holiday|personal_call>",
  "risk_flag": "<low|medium|high>",
  "reasoning": "<one sentence explaining the classification>"
}}
"""


# ── Agent class ───────────────────────────────────────────────────────────────

class SegmentationAgent:
    """
    Classifies a (customer, policy) pair into a behavioural segment.
    Call .run(customer, policy) → SegmentationResult
    """

    def __init__(self):
        self.client = get_gemini_client()
        self.model  = settings.model_classify
        logger.info(f"SegmentationAgent initialised | model={self.model}")

    def run(self, customer: Customer, policy: Policy) -> SegmentationResult:
        from datetime import date
        days_until_due = (policy.renewal_due_date - date.today()).days

        prompt = SEGMENTATION_PROMPT.format(
            name               = customer.name,
            age                = customer.age,
            occupation         = customer.occupation,
            city               = customer.city,
            state              = customer.state,
            preferred_channel  = customer.preferred_channel.value,
            preferred_language = customer.preferred_language.value,
            preferred_call_time= customer.preferred_call_time,
            policy_number      = policy.policy_number,
            product_type       = policy.product_type.value,
            product_name       = policy.product_name,
            annual_premium     = policy.annual_premium,
            sum_assured        = policy.sum_assured,
            years_completed    = policy.years_completed,
            tenure_years       = policy.tenure_years,
            days_until_due     = days_until_due,
            payment_history    = ", ".join(policy.payment_history) or "no history",
            has_auto_debit     = policy.has_auto_debit,
        )

        logger.debug(f"Segmenting {policy.policy_number} for {customer.name}")

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
        )

        raw = response.text.strip()
        # Strip markdown code fences if model adds them
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        data = json.loads(raw)

        result = SegmentationResult(
            customer_id           = customer.customer_id,
            policy_number         = policy.policy_number,
            segment               = CustomerSegment(data["segment"]),
            recommended_tone      = data["recommended_tone"],
            recommended_strategy  = data["recommended_strategy"],
            risk_flag             = data["risk_flag"],
            reasoning             = data["reasoning"],
        )

        logger.info(
            f"Segmented {policy.policy_number} | {customer.name} → "
            f"[{result.segment.value}] | risk={result.risk_flag}"
        )
        return result


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    from rich.console import Console
    from rich.table import Table
    from core.database import get_customer, get_policy, get_policies_due_within_days

    console = Console()
    agent   = SegmentationAgent()

    # Test against all 20 seeded policies
    policies = get_policies_due_within_days(60)
    console.print(f"\n[bold cyan]Segmenting {len(policies)} policies...[/bold cyan]\n")

    table = Table(title="Segmentation Results", show_header=True)
    table.add_column("Policy",    style="cyan",   min_width=13)
    table.add_column("Customer",  style="white",  min_width=16)
    table.add_column("Product",   style="yellow")
    table.add_column("Premium",   style="green")
    table.add_column("Due In",    style="magenta")
    table.add_column("Segment",   style="bold yellow", min_width=15)
    table.add_column("Tone",      style="blue")
    table.add_column("Strategy",  style="cyan",  min_width=18)
    table.add_column("Risk",      style="red")

    results = []
    for policy in policies:
        customer = get_customer(policy.customer_id)
        if not customer:
            continue
        from datetime import date
        days = (policy.renewal_due_date - date.today()).days
        result = agent.run(customer, policy)
        results.append((policy, customer, result))
        table.add_row(
            policy.policy_number,
            customer.name,
            policy.product_type.value,
            f"₹{policy.annual_premium:,.0f}",
            f"{days}d",
            result.segment.value,
            result.recommended_tone,
            result.recommended_strategy,
            result.risk_flag,
        )

    console.print(table)
    console.print(f"\n[green]✅ Segmented {len(results)} policies successfully.[/green]")
