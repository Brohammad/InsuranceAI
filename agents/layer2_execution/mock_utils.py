"""
agents/layer2_execution/mock_utils.py
──────────────────────────────────────
Shared mock/random output utilities for Layer 2 testing.

When settings.mock_delivery = True:
  - All delivery calls return randomly generated realistic outcomes
  - No real API calls to Twilio / SMTP / ElevenLabs / payment gateways
  - Useful for fast testing of the full pipeline without spending tokens
    on message generation or burning real API quotas

When mock_delivery = False:
  - Agents use their real LLM + delivery integrations
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime

from core.models import Channel, InteractionOutcome, Language


# ── Weighted outcome pools by channel ────────────────────────────────────────
# Weights reflect realistic delivery + engagement stats for Indian insurance

OUTCOME_WEIGHTS: dict[Channel, list[tuple[InteractionOutcome, float]]] = {
    Channel.WHATSAPP: [
        (InteractionOutcome.DELIVERED,   0.20),
        (InteractionOutcome.READ,        0.40),
        (InteractionOutcome.RESPONDED,   0.25),
        (InteractionOutcome.PAYMENT_MADE,0.10),
        (InteractionOutcome.NO_RESPONSE, 0.05),
    ],
    Channel.EMAIL: [
        (InteractionOutcome.DELIVERED,   0.30),
        (InteractionOutcome.READ,        0.35),
        (InteractionOutcome.RESPONDED,   0.10),
        (InteractionOutcome.PAYMENT_MADE,0.08),
        (InteractionOutcome.BOUNCED,     0.07),
        (InteractionOutcome.NO_RESPONSE, 0.10),
    ],
    Channel.VOICE: [
        (InteractionOutcome.RESPONDED,   0.45),
        (InteractionOutcome.PAYMENT_MADE,0.15),
        (InteractionOutcome.NO_RESPONSE, 0.25),
        (InteractionOutcome.OBJECTION,   0.10),
        (InteractionOutcome.OPT_OUT,     0.05),
    ],
    Channel.SMS: [
        (InteractionOutcome.DELIVERED,   0.60),
        (InteractionOutcome.READ,        0.25),
        (InteractionOutcome.NO_RESPONSE, 0.15),
    ],
    Channel.HUMAN: [
        (InteractionOutcome.RESPONDED,   0.70),
        (InteractionOutcome.PAYMENT_MADE,0.20),
        (InteractionOutcome.OPT_OUT,     0.10),
    ],
}

# Mock sentiment range per outcome
SENTIMENT_BY_OUTCOME: dict[InteractionOutcome, tuple[float, float]] = {
    InteractionOutcome.PAYMENT_MADE: (3.0,  8.0),
    InteractionOutcome.RESPONDED:    (0.0,  6.0),
    InteractionOutcome.READ:         (-1.0, 3.0),
    InteractionOutcome.DELIVERED:    (-1.0, 1.0),
    InteractionOutcome.NO_RESPONSE:  (-3.0, 0.0),
    InteractionOutcome.OBJECTION:    (-6.0, -1.0),
    InteractionOutcome.BOUNCED:      (-2.0, 0.0),
    InteractionOutcome.OPT_OUT:      (-8.0, -3.0),
    InteractionOutcome.ESCALATED:    (-5.0, -1.0),
    InteractionOutcome.SENT:         (-1.0, 1.0),
}


def mock_outcome(channel: Channel) -> InteractionOutcome:
    """Randomly pick a realistic outcome for a given channel."""
    pool = OUTCOME_WEIGHTS.get(channel, [(InteractionOutcome.DELIVERED, 1.0)])
    outcomes, weights = zip(*pool)
    return random.choices(outcomes, weights=weights, k=1)[0]


def mock_sentiment(outcome: InteractionOutcome) -> float:
    """Return a random sentiment score consistent with the outcome."""
    lo, hi = SENTIMENT_BY_OUTCOME.get(outcome, (-2.0, 2.0))
    return round(random.uniform(lo, hi), 2)


def mock_delivery_id(prefix: str = "MSG") -> str:
    """Generate a fake message/call delivery ID."""
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def mock_whatsapp_message(
    customer_name: str,
    policy_number: str,
    premium: float,
    due_days: int,
    language: Language,
    tone: str,
    strategy: str,
) -> str:
    """Return a canned realistic WhatsApp message (no LLM call)."""
    templates = {
        "hindi": (
            f"नमस्ते {customer_name} जी! 🙏\n\n"
            f"आपकी Suraksha Life पॉलिसी {policy_number} का नवीनीकरण "
            f"{due_days} दिनों में होना है।\n"
            f"प्रीमियम: ₹{premium:,.0f}\n\n"
            f"अभी भुगतान करें 👉 [PAYMENT_LINK]\n\n"
            f"किसी भी सहायता के लिए उत्तर दें।"
        ),
        "english": (
            f"Hello {customer_name}! 👋\n\n"
            f"Your Suraksha Life policy {policy_number} is due for renewal "
            f"in {due_days} day(s).\n"
            f"Premium: ₹{premium:,.0f}\n\n"
            f"Pay now 👉 [PAYMENT_LINK]\n\n"
            f"Reply to this message for any help."
        ),
        "tamil": (
            f"வணக்கம் {customer_name}! 🙏\n\n"
            f"உங்கள் Suraksha Life பாலிசி {policy_number} "
            f"{due_days} நாட்களில் புதுப்பிக்கப்பட வேண்டும்.\n"
            f"பிரீமியம்: ₹{premium:,.0f}\n\n"
            f"இப்போது செலுத்துங்கள் 👉 [PAYMENT_LINK]"
        ),
    }
    lang_key = language.value.lower()
    return templates.get(lang_key, templates["english"])


def mock_email_content(
    customer_name: str,
    policy_number: str,
    product_name: str,
    premium: float,
    sum_assured: float,
    due_days: int,
    language: Language,
    strategy: str,
) -> dict[str, str]:
    """Return a canned email subject + HTML body (no LLM call)."""
    subject = f"⏰ Policy Renewal Reminder: {policy_number} — Due in {due_days} days"
    body = f"""
<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto;">
<h2 style="color:#1a3c6e;">Suraksha Life Insurance</h2>
<p>Dear {customer_name},</p>
<p>Your <strong>{product_name}</strong> policy <strong>{policy_number}</strong>
is due for renewal in <strong>{due_days} day(s)</strong>.</p>
<table style="border-collapse:collapse;width:100%;">
  <tr><td style="padding:8px;border:1px solid #ddd;"><b>Annual Premium</b></td>
      <td style="padding:8px;border:1px solid #ddd;">₹{premium:,.0f}</td></tr>
  <tr><td style="padding:8px;border:1px solid #ddd;"><b>Sum Assured</b></td>
      <td style="padding:8px;border:1px solid #ddd;">₹{sum_assured:,.0f}</td></tr>
  <tr><td style="padding:8px;border:1px solid #ddd;"><b>Strategy</b></td>
      <td style="padding:8px;border:1px solid #ddd;">{strategy.replace('_',' ').title()}</td></tr>
</table>
<br/>
<a href="[PAYMENT_LINK]" style="background:#1a3c6e;color:#fff;padding:12px 24px;
   text-decoration:none;border-radius:4px;">Pay Now</a>
<p style="margin-top:24px;font-size:12px;color:#888;">
  Suraksha Life Insurance | IRDAI Reg No. 101 | 
  <a href="[UNSUBSCRIBE]">Unsubscribe</a>
</p>
</body></html>
"""
    return {"subject": subject, "body": body}


def mock_voice_script(
    customer_name: str,
    policy_number: str,
    premium: float,
    due_days: int,
    language: Language,
    tone: str,
    strategy: str,
) -> str:
    """Return a canned voice call script (no LLM call)."""
    greetings = {
        "hindi":    f"नमस्ते {customer_name} जी, मैं Suraksha Life Insurance से बोल रहा हूँ।",
        "english":  f"Hello {customer_name}, this is a call from Suraksha Life Insurance.",
        "tamil":    f"வணக்கம் {customer_name}, நான் Suraksha Life Insurance இலிருந்து பேசுகிறேன்.",
        "marathi":  f"नमस्कार {customer_name} जी, मी Suraksha Life Insurance कडून बोलतो आहे.",
        "telugu":   f"నమస్కారం {customer_name} గారు, నేను Suraksha Life Insurance నుండి మాట్లాడుతున్నాను.",
        "kannada":  f"ನಮಸ್ಕಾರ {customer_name} ಅವರೇ, ನಾನು Suraksha Life Insurance ನಿಂದ ಮಾತನಾಡುತ್ತಿದ್ದೇನೆ.",
        "malayalam":f"നമസ്കാരം {customer_name}, ഞാൻ Suraksha Life Insurance-ൽ നിന്ന് സംസാരിക്കുകയാണ്.",
        "bengali":  f"নমস্কার {customer_name}, আমি Suraksha Life Insurance থেকে কথা বলছি।",
        "gujarati": f"નમસ્તે {customer_name} જી, હું Suraksha Life Insurance તરફથી વાત કરી રહ્યો છું.",
    }
    lang_key = language.value.lower()
    greeting = greetings.get(lang_key, greetings["english"])
    return (
        f"{greeting}\n\n"
        f"Your policy {policy_number} is due for renewal in {due_days} day(s). "
        f"The annual premium is ₹{premium:,.0f}. "
        f"I'll send you a payment link on WhatsApp right away. "
        f"Is there anything I can help you with?"
    )


def mock_payment_link(policy_number: str, amount: float) -> dict:
    """Generate a mock UPI/payment link record."""
    txn_id = f"TXN{uuid.uuid4().hex[:12].upper()}"
    return {
        "txn_id":        txn_id,
        "policy_number": policy_number,
        "amount":        amount,
        "upi_link":      f"upi://pay?pa=renewai@suraksha&pn=Suraksha+Life&am={amount:.0f}&tn={txn_id}",
        "web_link":      f"https://pay.suraksha.in/renew/{txn_id}",
        "qr_data":       f"[QR:{txn_id}]",
        "expires_at":    "2026-04-01T23:59:59",
        "status":        "pending",
    }
