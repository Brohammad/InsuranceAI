"""
agents/layer3_quality/sentiment_agent.py
──────────────────────────────────────────
Sentiment Agent — scores inbound customer responses

Analyses customer reply messages to determine:
  • Sentiment polarity: positive / neutral / negative / hostile
  • Sentiment score: -1.0 (very negative) to +1.0 (very positive)
  • Intent: intending_to_pay | needs_time | objecting | ignoring | escalating
  • Language detected (for multilingual support)
  • Key topics mentioned (premium, lapse, family, returns, etc.)

Used by:
  • Quality Scoring Agent to rate interaction health
  • Dispatcher to decide next step (follow-up vs escalate vs stop)
  • Feedback Loop (Layer 4) to update lapse score

Uses gemini-2.5-flash for speed.
In mock mode: generates random but realistic sentiment outputs.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from loguru import logger
from google import genai

from core.config import settings
from core.models import Customer, Policy


# ── Result models ─────────────────────────────────────────────────────────────

class SentimentPolarity(str, Enum):
    POSITIVE = "positive"
    NEUTRAL  = "neutral"
    NEGATIVE = "negative"
    HOSTILE  = "hostile"


class CustomerIntent(str, Enum):
    INTENDING_TO_PAY = "intending_to_pay"
    NEEDS_TIME       = "needs_time"
    OBJECTING        = "objecting"
    IGNORING         = "ignoring"
    ESCALATING       = "escalating"
    ALREADY_PAID     = "already_paid"
    INTERESTED       = "interested"


@dataclass
class SentimentResult:
    polarity:        SentimentPolarity
    score:           float             # -1.0 to +1.0
    intent:          CustomerIntent
    detected_language: str            = "hindi"
    key_topics:      list[str]        = field(default_factory=list)
    confidence:      float            = 0.85
    summary:         str              = ""


# ── Mock data ──────────────────────────────────────────────────────────────────

_MOCK_POSITIVE_RESPONSES = [
    "Haan, main kal pay kar deta hoon.",
    "Thank you, I will renew by Friday.",
    "Bahut achha, please link bhejiye.",
    "OK send me the UPI ID.",
    "Main payment karne wala hoon, link dijiye.",
]
_MOCK_NEUTRAL_RESPONSES = [
    "Dekhunga.",
    "OK will see.",
    "Let me check with my family.",
    "Thoda time chahiye.",
    "Please call me after 2 days.",
]
_MOCK_NEGATIVE_RESPONSES = [
    "Abhi afford nahi kar sakta.",
    "Please don't call again.",
    "I need to think about it.",
    "Not interested right now.",
    "Bahut mehenga hai yeh policy.",
]
_MOCK_HOSTILE_RESPONSES = [
    "Stop calling me!",
    "Mujhe pareshan mat karo.",
    "Main complaint karunga.",
    "Remove my number immediately.",
]

_INTENT_WEIGHTS = {
    CustomerIntent.INTENDING_TO_PAY: 0.30,
    CustomerIntent.NEEDS_TIME:       0.25,
    CustomerIntent.OBJECTING:        0.20,
    CustomerIntent.IGNORING:         0.10,
    CustomerIntent.INTERESTED:       0.10,
    CustomerIntent.ESCALATING:       0.03,
    CustomerIntent.ALREADY_PAID:     0.02,
}

_POLARITY_WEIGHTS = {
    SentimentPolarity.POSITIVE: 0.35,
    SentimentPolarity.NEUTRAL:  0.35,
    SentimentPolarity.NEGATIVE: 0.22,
    SentimentPolarity.HOSTILE:  0.08,
}

_MOCK_TOPICS = [
    ["premium", "payment"],
    ["family", "protection"],
    ["lapse", "deadline"],
    ["returns", "investment"],
    ["time", "delay"],
    ["affordability", "cost"],
    ["service", "agent"],
]


def _mock_sentiment(customer: Customer, policy: Policy) -> SentimentResult:
    polarity = random.choices(
        list(_POLARITY_WEIGHTS.keys()),
        weights=list(_POLARITY_WEIGHTS.values()),
        k=1,
    )[0]
    intent = random.choices(
        list(_INTENT_WEIGHTS.keys()),
        weights=list(_INTENT_WEIGHTS.values()),
        k=1,
    )[0]

    score_map = {
        SentimentPolarity.POSITIVE:  round(random.uniform(0.4, 1.0), 2),
        SentimentPolarity.NEUTRAL:   round(random.uniform(-0.2, 0.4), 2),
        SentimentPolarity.NEGATIVE:  round(random.uniform(-0.7, -0.1), 2),
        SentimentPolarity.HOSTILE:   round(random.uniform(-1.0, -0.6), 2),
    }
    summary_map = {
        SentimentPolarity.POSITIVE: f"{customer.name.split()[0]} seems willing to pay — follow up with payment link.",
        SentimentPolarity.NEUTRAL:  f"{customer.name.split()[0]} is undecided — soft follow-up recommended.",
        SentimentPolarity.NEGATIVE: f"{customer.name.split()[0]} is resistant — reduce contact frequency.",
        SentimentPolarity.HOSTILE:  f"{customer.name.split()[0]} is hostile — consider human handoff or cooling period.",
    }

    return SentimentResult(
        polarity          = polarity,
        score             = score_map[polarity],
        intent            = intent,
        detected_language = customer.preferred_language.value,
        key_topics        = random.choice(_MOCK_TOPICS),
        confidence        = round(random.uniform(0.75, 0.97), 2),
        summary           = summary_map[polarity],
    )


# ── Prompt ────────────────────────────────────────────────────────────────────

SENTIMENT_PROMPT = """\
Analyse this customer message in the context of an insurance renewal reminder.

CUSTOMER: {name} | Language: {language} | Segment: {segment}
MESSAGE: "{message}"

Return JSON:
{{
  "polarity": "positive|neutral|negative|hostile",
  "score": -1.0 to 1.0,
  "intent": "intending_to_pay|needs_time|objecting|ignoring|escalating|already_paid|interested",
  "detected_language": "hindi|english|tamil|telugu|kannada|malayalam|bengali|marathi|gujarati",
  "key_topics": ["list", "of", "topics"],
  "confidence": 0.0-1.0,
  "summary": "one sentence action recommendation for the agent"
}}
"""


# ── Agent ─────────────────────────────────────────────────────────────────────

class SentimentAgent:
    """Analyses inbound customer message sentiment and intent."""

    def __init__(self):
        if not settings.mock_delivery:
            self._client = genai.Client(api_key=settings.gemini_api_key)
        logger.info(f"SentimentAgent ready | mock={settings.mock_delivery}")

    def analyse(
        self,
        customer: Customer,
        policy:   Policy,
        message:  str = "",
        segment:  str = "",
    ) -> SentimentResult:
        """Analyse customer message. Returns SentimentResult."""
        logger.debug(f"Sentiment analysis for {customer.name}")

        if settings.mock_delivery:
            result = _mock_sentiment(customer, policy)
            logger.info(
                f"Sentiment → {customer.name} | polarity={result.polarity.value} | "
                f"score={result.score:+.2f} | intent={result.intent.value} | mock=True"
            )
            return result

        if not message:
            return SentimentResult(
                polarity = SentimentPolarity.NEUTRAL,
                score    = 0.0,
                intent   = CustomerIntent.IGNORING,
                summary  = "No message to analyse.",
            )

        import json, re
        prompt = SENTIMENT_PROMPT.format(
            name     = customer.name,
            language = customer.preferred_language.value,
            segment  = segment,
            message  = message,
        )
        response = self._client.models.generate_content(
            model    = settings.model_classify,
            contents = prompt,
        )
        raw = response.text.strip()
        # remove fenced code blocks if the model wrapped JSON in ```json ```
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        # Robust JSON parsing: try direct load, then attempt to extract
        # a JSON object from the model text if the model added prose.
        try:
            data = json.loads(raw)
        except Exception:
            logger.warning("SentimentAgent: direct JSON parse failed, attempting to extract JSON object from model output")
            m = re.search(r"(\{.*\})", raw, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1))
                except Exception:
                    logger.exception("SentimentAgent: failed to parse extracted JSON; falling back to neutral result")
                    data = {}
            else:
                logger.warning("SentimentAgent: no JSON object found in model output; falling back to neutral result")
                data = {}
        # Safely coerce model outputs into enums/expected types with
        # sensible defaults if the model returned null/invalid values.
        pol = data.get("polarity") or "neutral"
        try:
            polarity_val = SentimentPolarity(pol)
        except Exception:
            polarity_val = SentimentPolarity.NEUTRAL

        try:
            score_val = float(data.get("score", 0.0) or 0.0)
        except Exception:
            score_val = 0.0

        intent_raw = data.get("intent") or "ignoring"
        try:
            intent_val = CustomerIntent(intent_raw)
        except Exception:
            intent_val = CustomerIntent.IGNORING

        detected_language = data.get("detected_language") or "hindi"
        key_topics = data.get("key_topics") or []
        try:
            confidence_val = float(data.get("confidence", 0.8) or 0.8)
        except Exception:
            confidence_val = 0.8

        result = SentimentResult(
            polarity=polarity_val,
            score=score_val,
            intent=intent_val,
            detected_language=detected_language,
            key_topics=key_topics,
            confidence=confidence_val,
            summary=data.get("summary", ""),
        )
        logger.info(
            f"Sentiment → {customer.name} | polarity={result.polarity.value} | "
            f"score={result.score:+.2f} | intent={result.intent.value}"
        )
        return result
