"""
agents/layer2_execution/email_agent.py
───────────────────────────────────────
Email Agent — Layer 2

Generates and (mock-)sends personalised renewal emails.

MOCK MODE: canned HTML templates, no SMTP call, random outcome.
REAL MODE: Gemini generation → SMTP send → open/click tracking.
"""

from __future__ import annotations

import smtplib
import uuid
from dataclasses import dataclass
from datetime import datetime, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from loguru import logger

from core.config import settings, get_gemini_client
from core.models import Channel, Customer, Interaction, InteractionOutcome, Policy
from agents.layer2_execution.mock_utils import (
    mock_delivery_id, mock_outcome, mock_sentiment, mock_email_content,
)
from agents.layer2_execution.language_utils import (
    build_language_instruction, get_mock_message, build_agent_context,
)


# ── Output ────────────────────────────────────────────────────────────────────

@dataclass
class EmailResult:
    message_id: str
    subject:    str
    body:       str
    outcome:    InteractionOutcome
    sentiment:  float
    sent_at:    datetime
    mock:       bool = True


# ── Prompt ────────────────────────────────────────────────────────────────────

EMAIL_PROMPT = """
You are an expert insurance renewal email writer at Suraksha Life Insurance.

{language_instruction}

Write a professional renewal reminder email in {language}. 
Include subject line prefixed with "SUBJECT:" then the body.
Use HTML formatting. Keep the email under 300 words.
Replace [PAYMENT_LINK] and [UNSUBSCRIBE] literally.

CUSTOMER: {name}
POLICY:   {policy_number} — {product_name}
PREMIUM:  ₹{premium:,}
SUM ASSURED: ₹{sum_assured:,}
DUE IN:   {due_days} days
TONE:     {tone}
STRATEGY: {strategy}
LANGUAGE: {language}

{agent_context}
"""


# ── Agent ─────────────────────────────────────────────────────────────────────

class EmailAgent:
    """Generates and (mock-)sends renewal emails."""

    def __init__(self):
        self.mock = settings.mock_delivery
        if not self.mock:
            self.client = get_gemini_client()
            self.model  = settings.model_execution
        logger.info(f"EmailAgent ready | mock={self.mock}")

    def _generate_email(
        self, customer: Customer, policy: Policy,
        tone: str, strategy: str, days: int,
    ) -> dict[str, str]:
        lang = customer.preferred_language.value
        if self.mock:
            first = customer.name.split()[0]
            body = get_mock_message(
                channel   = "email",
                language  = lang,
                name      = first,
                product   = policy.product_name,
                policy_no = policy.policy_number,
                due_date  = str(policy.renewal_due_date),
                premium   = f"{policy.annual_premium:,.0f}",
            )
            subject = get_mock_message(
                channel   = "email",
                language  = lang,
                name      = first,
                product   = policy.product_name,
                policy_no = policy.policy_number,
                due_date  = str(policy.renewal_due_date),
                premium   = f"{policy.annual_premium:,.0f}",
                subject   = True,
            )
            return {"subject": subject, "body": body}

        agent_ctx = build_agent_context(customer.customer_id, f"email renewal {strategy}", channel="email")
        prompt = EMAIL_PROMPT.format(
            language_instruction = build_language_instruction(lang, customer.name.split()[0]),
            name         = customer.name,
            policy_number= policy.policy_number,
            product_name = policy.product_name,
            premium      = policy.annual_premium,
            sum_assured  = policy.sum_assured,
            due_days     = days,
            tone         = tone,
            strategy     = strategy,
            language     = lang,
            agent_context= agent_ctx,
        )
        resp = self.client.models.generate_content(model=self.model, contents=prompt)
        text = resp.text.strip()

        # parse SUBJECT: line
        subject = f"Renewal Reminder: {policy.policy_number}"
        body    = text
        for line in text.splitlines():
            if line.upper().startswith("SUBJECT:"):
                subject = line[8:].strip()
                body    = text[text.index(line) + len(line):].strip()
                break
        return {"subject": subject, "body": body}

    def _send(self, to_email: str, subject: str, body: str) -> str:
        """Send via SMTP (or mock)."""
        if self.mock:
            return mock_delivery_id("EMAIL")

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = settings.email_from
            msg["To"]      = to_email
            msg["Message-ID"] = f"<{uuid.uuid4().hex}@suraksha.in>"
            msg.attach(MIMEText(body, "html"))

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.sendmail(settings.email_from, to_email, msg.as_string())
            return msg["Message-ID"]
        except Exception as e:
            logger.error(f"SMTP send failed: {e}")
            return mock_delivery_id("EMAIL-ERR")

    def run(
        self,
        customer:   Customer,
        policy:     Policy,
        journey_id: str,
        tone:       str = "professional",
        strategy:   str = "renewal_reminder",
    ) -> tuple[EmailResult, Interaction]:
        days = max((policy.renewal_due_date - date.today()).days, 0)
        logger.debug(f"Email → {customer.email} / {policy.policy_number}")

        content  = self._generate_email(customer, policy, tone, strategy, days)
        msg_id   = self._send(customer.email, content["subject"], content["body"])
        outcome  = mock_outcome(Channel.EMAIL) if self.mock else InteractionOutcome.SENT
        sentiment= mock_sentiment(outcome)
        now      = datetime.now()

        result = EmailResult(
            message_id = msg_id,
            subject    = content["subject"],
            body       = content["body"],
            outcome    = outcome,
            sentiment  = sentiment,
            sent_at    = now,
            mock       = self.mock,
        )

        interaction = Interaction(
            interaction_id  = f"INT-{uuid.uuid4().hex[:8].upper()}",
            journey_id      = journey_id,
            policy_number   = policy.policy_number,
            customer_id     = customer.customer_id,
            channel         = Channel.EMAIL,
            direction       = "outbound",
            message_content = f"[SUBJECT] {content['subject']}\n\n{content['body'][:500]}",
            language        = customer.preferred_language,
            sent_at         = now,
            outcome         = outcome,
            sentiment_score = sentiment,
        )

        logger.info(
            f"Email sent {msg_id} → {customer.name} | outcome={outcome.value} | mock={self.mock}"
        )
        return result, interaction
