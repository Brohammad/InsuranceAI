"""
agents/layer2_execution/whatsapp_agent.py
──────────────────────────────────────────
WhatsApp Agent — Layer 2

Sends personalised WhatsApp renewal messages.

MOCK MODE (settings.mock_delivery = True):
  - Uses canned templates from mock_utils (no LLM, no Twilio)
  - Returns a random realistic delivery outcome
  - Fast — no network calls

REAL MODE (settings.mock_delivery = False):
  - Generates message via Gemini (model_execution)
  - Sends via Twilio WhatsApp Business API
  - Tracks delivery status
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, date

from loguru import logger

from core.config import settings, get_gemini_client
from core.models import Channel, Customer, Interaction, InteractionOutcome, Language, Policy
from agents.layer2_execution.mock_utils import (
    mock_delivery_id, mock_outcome, mock_sentiment, mock_whatsapp_message,
)
from agents.layer2_execution.language_utils import (
    build_language_instruction, get_mock_message, build_agent_context,
)


# ── Output ────────────────────────────────────────────────────────────────────

@dataclass
class WhatsAppResult:
    message_id:   str
    message_body: str
    outcome:      InteractionOutcome
    sentiment:    float
    delivered_at: datetime
    mock:         bool = True


# ── Prompt ────────────────────────────────────────────────────────────────────

WA_PROMPT = """
You are a WhatsApp communication specialist at Suraksha Life Insurance.

{language_instruction}

Write a personalised WhatsApp renewal message in {language}.
Keep it concise (max 5 lines), warm, and include a clear call-to-action.
Do NOT include markdown or HTML — plain text with emojis only.
Replace [PAYMENT_LINK] literally — the system will substitute the real link.

CUSTOMER: {name}
POLICY:   {policy_number} ({product_type})
PREMIUM:  ₹{premium:,}
DUE IN:   {due_days} days
TONE:     {tone}
STRATEGY: {strategy}
LANGUAGE: {language}

{agent_context}

Write ONLY the message text, nothing else.
"""


# ── Agent ─────────────────────────────────────────────────────────────────────

class WhatsAppAgent:
    """Generates and (mock-)sends WhatsApp renewal messages."""

    def __init__(self):
        self.mock = settings.mock_delivery
        if not self.mock:
            self.client = get_gemini_client()
            self.model  = settings.model_execution
        logger.info(f"WhatsAppAgent ready | mock={self.mock}")

    def _generate_message(
        self, customer: Customer, policy: Policy,
        tone: str, strategy: str, days: int,
    ) -> str:
        lang = customer.preferred_language.value
        if self.mock:
            return get_mock_message(
                channel   = "whatsapp",
                language  = lang,
                name      = customer.name.split()[0],
                product   = policy.product_type.value if hasattr(policy, "product_type") else "Life",
                policy_no = policy.policy_number,
                due_date  = str(policy.renewal_due_date),
                premium   = f"{policy.annual_premium:,.0f}",
            )

        agent_ctx = build_agent_context(customer.customer_id, f"whatsapp renewal {strategy}", channel="whatsapp")
        prompt = WA_PROMPT.format(
            language_instruction = build_language_instruction(lang, customer.name.split()[0]),
            name         = customer.name,
            policy_number= policy.policy_number,
            product_type = policy.product_type.value,
            premium      = policy.annual_premium,
            due_days     = days,
            tone         = tone,
            strategy     = strategy,
            language     = lang,
            agent_context= agent_ctx,
        )
        resp = self.client.models.generate_content(model=self.model, contents=prompt)
        return resp.text.strip()

    def _send(self, to_number: str, message: str) -> str:
        """Send via Twilio (or mock)."""
        if self.mock:
            return mock_delivery_id("WA")

        try:
            from twilio.rest import Client
            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            msg = client.messages.create(
                from_ = settings.twilio_whatsapp_from,
                body  = message,
                to    = f"whatsapp:{to_number}",
            )
            return msg.sid
        except Exception as e:
            logger.error(f"Twilio send failed: {e}")
            return mock_delivery_id("WA-ERR")

    def run(
        self,
        customer: Customer,
        policy:   Policy,
        journey_id: str,
        tone:     str = "friendly",
        strategy: str = "renewal_reminder",
    ) -> tuple[WhatsAppResult, Interaction]:
        days = max((policy.renewal_due_date - date.today()).days, 0)
        logger.debug(f"WhatsApp → {customer.name} / {policy.policy_number}")

        body    = self._generate_message(customer, policy, tone, strategy, days)
        msg_id  = self._send(customer.whatsapp_number or customer.phone, body)
        outcome = InteractionOutcome.DELIVERED if self.mock else InteractionOutcome.SENT

        # mock: randomise a more interesting outcome for testing
        if self.mock:
            outcome = mock_outcome(Channel.WHATSAPP)

        sentiment = mock_sentiment(outcome)
        now       = datetime.now()

        result = WhatsAppResult(
            message_id   = msg_id,
            message_body = body,
            outcome      = outcome,
            sentiment    = sentiment,
            delivered_at = now,
            mock         = self.mock,
        )

        interaction = Interaction(
            interaction_id  = f"INT-{uuid.uuid4().hex[:8].upper()}",
            journey_id      = journey_id,
            policy_number   = policy.policy_number,
            customer_id     = customer.customer_id,
            channel         = Channel.WHATSAPP,
            direction       = "outbound",
            message_content = body,
            language        = customer.preferred_language,
            sent_at         = now,
            outcome         = outcome,
            sentiment_score = sentiment,
        )

        logger.info(
            f"WA sent {msg_id} → {customer.name} | outcome={outcome.value} | mock={self.mock}"
        )
        return result, interaction

    # ── Backward-compat aliases used by the test suite ──────────────────────

    def _mock_send(
        self, customer: Customer, policy: Policy,
        tone: str = "friendly", strategy: str = "renewal_reminder",
    ) -> "WhatsAppResult":
        """Alias: runs the agent in mock mode and returns just the result (no Interaction)."""
        days = max((policy.renewal_due_date - date.today()).days, 0)
        body = self._generate_message(customer, policy, tone, strategy, days)
        outcome = mock_outcome(Channel.WHATSAPP)
        return WhatsAppResult(
            message_id   = mock_delivery_id("WA"),
            message_body = body,
            outcome      = outcome,
            sentiment    = mock_sentiment(outcome),
            delivered_at = datetime.now(),
            mock         = True,
        )

    def send(
        self, customer: Customer, policy: Policy,
        tone: str = "friendly", strategy: str = "renewal_reminder",
        journey_id: str = "J-TEST",
    ) -> "WhatsAppResult":
        """Alias: generates message via Gemini and returns result (no Interaction)."""
        result, _ = self.run(customer, policy, journey_id=journey_id, tone=tone, strategy=strategy)
        return result
