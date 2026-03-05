"""
agents/layer3_quality/critique_agent.py
────────────────────────────────────────
Critique Agent — pre-send message review

Uses gemini-2.5-pro to review a proposed outbound message for:
  • Tone appropriateness (empathy vs pushiness)
  • Factual accuracy (policy numbers, premium amounts)
  • Language quality (grammar, readability in target language)
  • Personalisation depth (does it feel generic?)
  • Conversion likelihood (1-10)

Returns a CritiqueResult with approved/rejected + optional rewrite.
In mock mode: returns a random but realistic critique.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from loguru import logger
from google import genai

from core.config import settings
from core.models import CritiqueResult, Customer, Policy


# ── Prompt ────────────────────────────────────────────────────────────────────

CRITIQUE_PROMPT = """\
You are a senior communication quality reviewer for Suraksha Life Insurance.
Review the following outbound renewal message and return a structured critique.

CUSTOMER PROFILE:
  Name:     {name}
  Segment:  {segment}
  Language: {language}
  Age:      {age}
  Occupation: {occupation}

POLICY:
  Number:         {policy_number}
  Annual Premium: ₹{premium:,}
  Days to Lapse:  {days_to_lapse}
  Lapse Score:    {lapse_score}/100

MESSAGE (channel={channel}):
{message}

Return a JSON object with these fields:
{{
  "approved": true/false,
  "tone_score": 1-10,
  "accuracy_score": 1-10,
  "personalisation_score": 1-10,
  "conversion_likelihood": 1-10,
  "issues": ["list of specific issues found"],
  "rewrite": "improved version if approved=false, else null",
  "overall_verdict": "one sentence summary"
}}

Be strict. Reject any message that is pushy, factually wrong, or feels generic.
"""

# ── Mock helpers ───────────────────────────────────────────────────────────────

_MOCK_ISSUES = [
    ["Slightly generic opening — missing customer's name in first line."],
    ["Good message — no issues found."],
    ["Premium amount not mentioned explicitly."],
    ["Tone is slightly urgent; could feel pressuring to price-sensitive customer."],
    ["Missing policy expiry date — critical for urgency."],
    [],
    ["Language switches mid-message — keep consistent."],
    ["Call-to-action link not prominent enough."],
]

_MOCK_VERDICTS = [
    "Message is empathetic and personalised; approved for sending.",
    "Good tone and accuracy; minor personalisation improvements possible.",
    "Message approved — conversion likelihood is high for this segment.",
    "Slightly generic; recommended rewrite will improve click-through.",
    "Accurate and appropriately urgent without being pushy.",
]

_MOCK_REWRITE = (
    "Namaste {name} ji, aapki {policy_number} policy ka renewal {days} din mein "
    "due hai. Hamare paas aapke liye ek special option hai — abhi ₹{premium:,} "
    "bhejein aur apni family ki suraksha sunischit karein. 🙏"
)


def _mock_critique(customer: Customer, policy: Policy, channel: str) -> CritiqueResult:
    from datetime import date
    days_to_lapse = (policy.renewal_due_date - date.today()).days
    tone          = random.randint(6, 10)
    accuracy      = random.randint(7, 10)
    personalise   = random.randint(5, 10)
    conversion    = random.randint(5, 10)
    issues        = random.choice(_MOCK_ISSUES)
    approved      = (tone >= 7 and accuracy >= 7 and len(issues) <= 1)
    rewrite       = None
    if not approved:
        rewrite = _MOCK_REWRITE.format(
            name         = customer.name.split()[0],
            policy_number= policy.policy_number,
            days         = max(days_to_lapse, 0),
            premium      = int(policy.annual_premium),
        )
    return CritiqueResult(
        approved              = approved,
        tone_score            = tone,
        accuracy_score        = accuracy,
        personalisation_score = personalise,
        conversion_likelihood = conversion,
        issues                = issues,
        rewrite               = rewrite,
        overall_verdict       = random.choice(_MOCK_VERDICTS),
    )


# ── Agent ─────────────────────────────────────────────────────────────────────

class CritiqueAgent:
    """Pre-send message reviewer using gemini-2.5-pro (or mock)."""

    def __init__(self):
        if not settings.mock_delivery:
            self._client = genai.Client(api_key=settings.gemini_api_key)
        logger.info(f"CritiqueAgent ready | mock={settings.mock_delivery}")

    def run(
        self,
        customer:  Customer,
        policy:    Policy,
        message:   str,
        channel:   str,
        segment:   str = "",
        lapse_score: int = 50,
    ) -> CritiqueResult:
        """Review a message. Returns CritiqueResult with approved flag."""

        logger.debug(f"Critiquing {channel} message for {customer.name}")

        if settings.mock_delivery:
            result = _mock_critique(customer, policy, channel)
            logger.info(
                f"Critique → {customer.name} | {channel} | "
                f"approved={result.approved} | tone={result.tone_score} | "
                f"conversion={result.conversion_likelihood} | mock=True"
            )
            return result

        import json, re
        from datetime import date
        prompt = CRITIQUE_PROMPT.format(
            name         = customer.name,
            segment      = segment,
            language     = customer.preferred_language.value,
            age          = customer.age,
            occupation   = customer.occupation,
            policy_number= policy.policy_number,
            premium      = int(policy.annual_premium),
            days_to_lapse= (policy.renewal_due_date - date.today()).days,
            lapse_score  = lapse_score,
            channel      = channel,
            message      = message,
        )
        import json, re
        response = self._client.models.generate_content(
            model    = settings.model_critique,
            contents = prompt,
        )
        raw = response.text.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        # Robust JSON parsing: try direct load, then attempt to extract
        # a JSON object from model output if the model added prose.
        try:
            data = json.loads(raw)
        except Exception:
            logger.warning("CritiqueAgent: direct JSON parse failed, attempting to extract JSON object from model output")
            m = re.search(r"(\{.*\})", raw, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1))
                except Exception:
                    logger.exception("CritiqueAgent: failed to parse extracted JSON; falling back to empty result")
                    data = {}
            else:
                logger.warning("CritiqueAgent: no JSON object found in model output; falling back to empty result")
                data = {}

        # Normalize fields to avoid validation errors (models may return dicts/lists)
        issues = data.get("issues", [])
        if isinstance(issues, str):
            issues = [issues]
        elif issues is None:
            issues = []

        rewrite = data.get("rewrite")
        if isinstance(rewrite, dict):
            # Common case: model returns {'subject':..., 'body':...}
            if "subject" in rewrite and "body" in rewrite:
                rewrite = f"{rewrite.get('subject','').strip()}\n\n{rewrite.get('body','').strip()}".strip()
            else:
                # Fallback: stringify the dict
                try:
                    rewrite = json.dumps(rewrite, ensure_ascii=False)
                except Exception:
                    rewrite = str(rewrite)
        elif isinstance(rewrite, list):
            rewrite = "\n".join(str(x) for x in rewrite)
        elif rewrite is None:
            rewrite = None
        else:
            rewrite = str(rewrite)

        result = CritiqueResult(
            approved              = bool(data.get("approved", False)),
            tone_score            = int(data.get("tone_score", 5)),
            accuracy_score        = int(data.get("accuracy_score", 5)),
            personalisation_score = int(data.get("personalisation_score", 5)),
            conversion_likelihood = int(data.get("conversion_likelihood", 5)),
            issues                = issues,
            rewrite               = rewrite,
            overall_verdict       = data.get("overall_verdict", ""),
        )
        logger.info(
            f"Critique → {customer.name} | {channel} | "
            f"approved={result.approved} | conversion={result.conversion_likelihood}"
        )
        return result
