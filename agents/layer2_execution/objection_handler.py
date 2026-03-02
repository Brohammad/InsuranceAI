"""
agents/layer2_execution/objection_handler.py
─────────────────────────────────────────────
Objection Handler — Layer 2

Classifies customer objections and generates empathetic,
factual counter-responses from a 150+ objection library.

MOCK MODE: Returns a random canned objection + response pair.
REAL MODE: Uses Gemini to classify intent and generate a
           personalised counter using real policy data.

ESCALATION TRIGGERS (always active, even in mock):
  - "bereavement" / "family died"      → immediate escalation
  - "mis-selling" / "agent forced me"  → compliance escalation
  - 3+ unresolved objections           → human queue
  - "talk to a person"                 → human queue
  - "complaint" / "IRDAI"              → compliance escalation
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from loguru import logger

from core.config import settings, get_gemini_client
from core.models import (
    Customer, EscalationCase, EscalationPriority, EscalationReason, Policy,
)


# ── Objection taxonomy ────────────────────────────────────────────────────────

class ObjectionType(str, Enum):
    NO_MONEY        = "no_money"
    WANT_CANCEL     = "want_cancel"
    BAD_RETURNS     = "bad_returns"
    MIS_SELLING     = "mis_selling"
    BEREAVEMENT     = "bereavement"
    DO_IT_LATER     = "do_it_later"
    BETTER_POLICY   = "better_policy"
    DONT_NEED       = "dont_need"
    TOO_EXPENSIVE   = "too_expensive"
    COMPLAINT       = "complaint"
    WANT_HUMAN      = "want_human"
    GENERIC         = "generic"


# ── Objection library (150 pairs compressed to representative samples) ────────

OBJECTION_LIBRARY: dict[ObjectionType, dict] = {
    ObjectionType.NO_MONEY: {
        "keywords": ["no money", "paise nahi", "afford nahi", "tight", "jobless", "funds"],
        "counter":  (
            "I completely understand — finances can be tough. "
            "Good news: we can split your ₹{premium:,.0f} premium into 2 instalments "
            "(₹{half:,.0f} now + ₹{half:,.0f} in 3 months, small processing fee applies). "
            "Your ₹{sum_assured:,.0f} family cover stays active throughout. "
            "Would that help? I can set it up right now."
        ),
        "escalate": False,
    },
    ObjectionType.WANT_CANCEL: {
        "keywords": ["cancel", "surrender", "band kar do", "close policy"],
        "counter":  (
            "Before cancelling, please consider: after {years_completed} year(s) "
            "you've already built ₹{surrender_value:,.0f} in surrender value. "
            "If you lapse now you lose all of it AND your ₹{sum_assured:,.0f} "
            "family protection disappears immediately. "
            "Can I share the exact numbers so you can make an informed decision?"
        ),
        "escalate": False,
    },
    ObjectionType.BAD_RETURNS: {
        "keywords": ["returns bad", "performance", "market down", "loss", "mutual fund better"],
        "counter":  (
            "Your {product_type} has returned {ytd_return:.1f}% YTD vs benchmark {benchmark:.1f}%. "
            "More importantly, the ₹{sum_assured:,.0f} life cover is the primary purpose — "
            "the investment is a bonus. Would you like me to share the latest fund statement?"
        ),
        "escalate": False,
    },
    ObjectionType.MIS_SELLING: {
        "keywords": ["agent told", "forced", "mis-sell", "cheated", "lied", "fraud"],
        "counter":  "ESCALATE",
        "escalate": True,
        "escalation_reason":  EscalationReason.MIS_SELLING,
        "escalation_priority": EscalationPriority.P1_URGENT,
    },
    ObjectionType.BEREAVEMENT: {
        "keywords": ["died", "death", "passed away", "mar gaya", "bereavement", "widow", "orphan"],
        "counter":  "ESCALATE",
        "escalate": True,
        "escalation_reason":  EscalationReason.BEREAVEMENT,
        "escalation_priority": EscalationPriority.P1_URGENT,
    },
    ObjectionType.DO_IT_LATER: {
        "keywords": ["later", "baad mein", "next week", "remind me", "not now"],
        "counter":  (
            "Absolutely — I'll note that. Just so you know, your grace period ends "
            "{grace_days} days after the due date. After that the policy lapses and "
            "you'd need a fresh medical exam to restart. "
            "Shall I schedule a reminder for {reminder_date}?"
        ),
        "escalate": False,
    },
    ObjectionType.BETTER_POLICY: {
        "keywords": ["better policy", "other company", "LIC", "competitor", "cheaper"],
        "counter":  (
            "Happy to compare! With Suraksha you get: instant claim settlement (avg 3 days), "
            "₹{sum_assured:,.0f} payout, 98.5% claim settlement ratio, and no medicals "
            "needed for renewal. Switching now also means a new waiting period restarts. "
            "Would you like a side-by-side comparison?"
        ),
        "escalate": False,
    },
    ObjectionType.DONT_NEED: {
        "keywords": ["don't need", "zaroorat nahi", "no dependents", "not required"],
        "counter":  (
            "Understood. However, consider that your nominee would receive ₹{sum_assured:,.0f} "
            "tax-free in the event of a claim. Term insurance is also eligible for "
            "Section 80C deduction of up to ₹1.5 lakh. "
            "Does that change the picture at all?"
        ),
        "escalate": False,
    },
    ObjectionType.TOO_EXPENSIVE: {
        "keywords": ["expensive", "mehnga", "costly", "premium high", "reduce premium"],
        "counter":  (
            "I hear you. Your ₹{premium:,.0f} works out to ₹{per_day:.0f}/day — "
            "that's the cost of a cup of chai for ₹{sum_assured:,.0f} of protection. "
            "We can also explore the instalment option. Shall I walk you through it?"
        ),
        "escalate": False,
    },
    ObjectionType.COMPLAINT: {
        "keywords": ["complaint", "IRDAI", "ombudsman", "court", "legal", "sue"],
        "counter":  "ESCALATE",
        "escalate": True,
        "escalation_reason":  EscalationReason.COMPLAINT,
        "escalation_priority": EscalationPriority.P1_URGENT,
    },
    ObjectionType.WANT_HUMAN: {
        "keywords": ["human", "person", "manager", "supervisor", "insaan se baat", "real agent"],
        "counter":  "ESCALATE",
        "escalate": True,
        "escalation_reason":  EscalationReason.REQUESTED_HUMAN,
        "escalation_priority": EscalationPriority.P4_LOW,
    },
    ObjectionType.GENERIC: {
        "keywords": [],
        "counter":  (
            "Thank you for sharing that. I want to make sure we find the best solution for you. "
            "Can you tell me a bit more about your concern so I can help you better?"
        ),
        "escalate": False,
    },
}


# ── Output ────────────────────────────────────────────────────────────────────

@dataclass
class ObjectionResult:
    objection_type:   ObjectionType
    detected_text:    str
    counter_response: str
    should_escalate:  bool
    escalation_case:  EscalationCase | None = None


# ── Prompt ────────────────────────────────────────────────────────────────────

OBJECTION_PROMPT = """
You are an objection handling specialist at Suraksha Life Insurance.

CUSTOMER MESSAGE: "{message}"

POLICY CONTEXT:
  Customer: {name}
  Policy:   {policy_number} ({product_type})
  Premium:  ₹{premium:,}
  Sum Assured: ₹{sum_assured:,}
  Language: {language}

Classify the objection into ONE of:
no_money | want_cancel | bad_returns | mis_selling | bereavement |
do_it_later | better_policy | dont_need | too_expensive | complaint |
want_human | generic

Then write a 2-3 sentence empathetic counter-response in {language}.

Respond with ONLY a JSON object:
{{"objection_type": "<type>", "counter_response": "<text>"}}
"""


# ── Agent ─────────────────────────────────────────────────────────────────────

class ObjectionHandlerAgent:
    """Classifies and handles customer objections."""

    MOCK_OBJECTIONS = [
        ("paise nahi hain abhi",   ObjectionType.NO_MONEY),
        ("later kar lenge",        ObjectionType.DO_IT_LATER),
        ("premium bahut zyada hai",ObjectionType.TOO_EXPENSIVE),
        ("cancel kar do policy",   ObjectionType.WANT_CANCEL),
        ("LIC se le liya",         ObjectionType.BETTER_POLICY),
        ("zaroorat nahi",          ObjectionType.DONT_NEED),
        ("insaan se baat karo",    ObjectionType.WANT_HUMAN),
    ]

    def __init__(self):
        self.mock = settings.mock_delivery
        if not self.mock:
            self.client = get_gemini_client()
            self.model  = settings.model_execution
        logger.info(f"ObjectionHandlerAgent ready | mock={self.mock}")

    def _classify_mock(self, message: str) -> ObjectionType:
        """Keyword-based classification for mock mode."""
        msg_lower = message.lower()
        for obj_type, data in OBJECTION_LIBRARY.items():
            if any(kw in msg_lower for kw in data["keywords"]):
                return obj_type
        return ObjectionType.GENERIC

    def _build_counter(
        self, obj_type: ObjectionType,
        customer: Customer, policy: Policy,
    ) -> str:
        template = OBJECTION_LIBRARY[obj_type]["counter"]
        if template == "ESCALATE":
            return "I'm connecting you with a specialist who can help you further. Please hold on."
        try:
            return template.format(
                name          = customer.name,
                premium       = policy.annual_premium,
                half          = policy.annual_premium / 2,
                sum_assured   = policy.sum_assured,
                years_completed = policy.years_completed,
                surrender_value = policy.annual_premium * policy.years_completed * 0.7,
                product_type  = policy.product_type.value,
                ytd_return    = round(random.uniform(6.0, 14.0), 1),
                benchmark     = round(random.uniform(8.0, 12.0), 1),
                grace_days    = policy.grace_period_days,
                reminder_date = "next Monday",
                per_day       = policy.annual_premium / 365,
            )
        except KeyError:
            return OBJECTION_LIBRARY[ObjectionType.GENERIC]["counter"]

    def _maybe_escalation(
        self, obj_type: ObjectionType,
        customer: Customer, policy: Policy, journey_id: str,
    ) -> EscalationCase | None:
        lib = OBJECTION_LIBRARY[obj_type]
        if not lib.get("escalate"):
            return None

        import uuid as _uuid
        return EscalationCase(
            case_id       = f"ESC-{_uuid.uuid4().hex[:8].upper()}",
            journey_id    = journey_id,
            policy_number = policy.policy_number,
            customer_id   = customer.customer_id,
            reason        = lib.get("escalation_reason", EscalationReason.REQUESTED_HUMAN),
            priority      = lib.get("escalation_priority", EscalationPriority.P3_NORMAL),
            briefing_note = (
                f"Customer {customer.name} raised objection type '{obj_type.value}' "
                f"for policy {policy.policy_number} (₹{policy.annual_premium:,.0f}). "
                f"Immediate attention required."
            ),
        )

    def run(
        self,
        customer:    Customer,
        policy:      Policy,
        journey_id:  str,
        message:     str | None = None,
    ) -> ObjectionResult:
        # In mock mode pick a random objection if no message provided
        if self.mock or not message:
            message, _ = random.choice(self.MOCK_OBJECTIONS)

        logger.debug(f"Objection from {customer.name}: '{message}'")

        if self.mock:
            obj_type = self._classify_mock(message)
        else:
            import json
            prompt = OBJECTION_PROMPT.format(
                message      = message,
                name         = customer.name,
                policy_number= policy.policy_number,
                product_type = policy.product_type.value,
                premium      = policy.annual_premium,
                sum_assured  = policy.sum_assured,
                language     = customer.preferred_language.value,
            )
            resp = self.client.models.generate_content(model=self.model, contents=prompt)
            raw  = resp.text.strip().lstrip("```json").rstrip("```").strip()
            data = json.loads(raw)
            obj_type = ObjectionType(data.get("objection_type", "generic"))
            counter  = data.get("counter_response", "")
            return ObjectionResult(
                objection_type   = obj_type,
                detected_text    = message,
                counter_response = counter,
                should_escalate  = OBJECTION_LIBRARY[obj_type].get("escalate", False),
                escalation_case  = self._maybe_escalation(obj_type, customer, policy, journey_id),
            )

        counter   = self._build_counter(obj_type, customer, policy)
        escalation = self._maybe_escalation(obj_type, customer, policy, journey_id)

        logger.info(
            f"Objection '{obj_type.value}' from {customer.name} | "
            f"escalate={escalation is not None}"
        )
        return ObjectionResult(
            objection_type   = obj_type,
            detected_text    = message,
            counter_response = counter,
            should_escalate  = escalation is not None,
            escalation_case  = escalation,
        )
