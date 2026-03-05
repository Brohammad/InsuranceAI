"""
agents/layer3_quality/safety_agent.py
───────────────────────────────────────
Safety Agent — real-time distress & vulnerability detection

Monitors ALL inbound customer messages for:
  • Financial distress signals (can't afford, lost job, medical bills)
  • Emotional distress / bereavement
  • Mental health / crisis signals (extreme language)
  • Coercion / mis-selling claims
  • Vulnerable customer indicators (elderly confusion, language barrier)

On detection:
  • Flags the interaction with a safety_flag
  • Raises escalation with priority P1_URGENT for crisis / P2_HIGH for distress
  • Stops further automated messaging for that journey

Uses gemini-2.5-flash for real-time speed.
In mock mode: randomly picks a safety outcome.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from loguru import logger
from google import genai

from core.config import settings, get_gemini_client
from core.models import (
    Customer, EscalationCase, EscalationPriority, EscalationReason,
    Policy,
)


# ── Result model ──────────────────────────────────────────────────────────────

class SafetyFlag(str, Enum):
    CLEAR           = "clear"
    FINANCIAL_STRESS= "financial_stress"
    EMOTIONAL_DISTRESS = "emotional_distress"
    CRISIS          = "crisis"
    MIS_SELLING     = "mis_selling"
    VULNERABLE      = "vulnerable"
    BEREAVEMENT     = "bereavement"


@dataclass
class SafetyResult:
    flag:            SafetyFlag      = SafetyFlag.CLEAR
    confidence:      float           = 1.0            # 0.0–1.0
    trigger_phrases: list[str]      = field(default_factory=list)
    should_escalate: bool           = False
    escalation_case: EscalationCase | None = None
    agent_note:      str            = ""
    # Backward-compat fields used by tests
    is_safe:         bool           = True
    distress_detected: bool         = False
    flags:           list[str]      = field(default_factory=list)
    severity:        str            = "low"
    action_required: str            = ""

    def __post_init__(self):
        # Sync is_safe ↔ flag if caller used old API
        if not self.is_safe and self.flag == SafetyFlag.CLEAR:
            # Old-API caller passed is_safe=False — infer flag from severity
            sev = self.severity or "low"
            if sev == "critical":
                self.flag = SafetyFlag.CRISIS
            elif sev == "high":
                self.flag = SafetyFlag.EMOTIONAL_DISTRESS
            else:
                self.flag = SafetyFlag.FINANCIAL_STRESS
            self.should_escalate = True
        elif self.flag != SafetyFlag.CLEAR:
            # New-API — keep is_safe in sync
            self.is_safe = False


# ── Keyword patterns (fast pre-filter before LLM) ─────────────────────────────

_CRISIS_KEYWORDS = [
    "suicide", "khud ko hurt", "nahi rehna chahta", "jeena nahi",
    "harm myself", "end it all", "zindagi khatam",
]
_DISTRESS_KEYWORDS = [
    "naukri gayi", "lost job", "hospital mein", "bimar", "paisa nahi",
    "debt", "karz", "afford nahi", "broke", "medical bill",
    "death in family", "husband passed", "wife expired", "mera beta",
    "shok", "grief",
]
_MISSELLING_KEYWORDS = [
    "bina bataye", "agent ne galat kaha", "cheated", "fraud",
    "mis-sold", "forced", "not explained", "bata nahi tha",
]
_VULNERABLE_KEYWORDS = [
    "samajh nahi aaya", "bujurg", "i don't understand", "confused",
    "anpad", "padha likha nahi", "meri beti padhti hai",
]


def _keyword_precheck(message: str) -> SafetyFlag:
    msg = message.lower()
    for kw in _CRISIS_KEYWORDS:
        if kw in msg:
            return SafetyFlag.CRISIS
    for kw in _DISTRESS_KEYWORDS:
        if kw in msg:
            return SafetyFlag.FINANCIAL_STRESS if "naukri" in kw or "paisa" in kw else SafetyFlag.EMOTIONAL_DISTRESS
    for kw in _MISSELLING_KEYWORDS:
        if kw in msg:
            return SafetyFlag.MIS_SELLING
    for kw in _VULNERABLE_KEYWORDS:
        if kw in msg:
            return SafetyFlag.VULNERABLE
    return SafetyFlag.CLEAR


# ── Mock helpers ───────────────────────────────────────────────────────────────

_MOCK_MESSAGES = [
    "Main abhi premium nahi bhar sakta, naukri gayi hai.",
    "Sab theek hai, main pay karunga.",
    "Yeh policy mere agent ne bina bataye di thi.",
    "Please call back later, everything is fine.",
    "Ghar mein koi bimar hai, abhi focus nahi kar sakta.",
    "I want to renew, please send payment link.",
    "Main samajh nahi paa raha hoon, please explain.",
    "OK I will pay tomorrow.",
]

_MOCK_FLAG_WEIGHTS = {
    SafetyFlag.CLEAR:             0.65,
    SafetyFlag.FINANCIAL_STRESS:  0.12,
    SafetyFlag.EMOTIONAL_DISTRESS:0.08,
    SafetyFlag.VULNERABLE:        0.07,
    SafetyFlag.MIS_SELLING:       0.05,
    SafetyFlag.CRISIS:            0.03,
}


def _mock_safety(customer: Customer, policy: Policy, journey_id: str) -> SafetyResult:
    flag = random.choices(
        list(_MOCK_FLAG_WEIGHTS.keys()),
        weights=list(_MOCK_FLAG_WEIGHTS.values()),
        k=1,
    )[0]
    confidence    = round(random.uniform(0.70, 0.98), 2)
    should_esc    = flag in (SafetyFlag.CRISIS, SafetyFlag.MIS_SELLING, SafetyFlag.EMOTIONAL_DISTRESS)
    esc_case      = None

    if should_esc:
        priority = (
            EscalationPriority.P1_URGENT if flag == SafetyFlag.CRISIS
            else EscalationPriority.P2_HIGH
        )
        reason_map = {
            SafetyFlag.CRISIS:            EscalationReason.DISTRESS,
            SafetyFlag.MIS_SELLING:       EscalationReason.MIS_SELLING,
            SafetyFlag.EMOTIONAL_DISTRESS:EscalationReason.DISTRESS,
        }
        esc_case = EscalationCase(
            case_id       = f"ESC-SAF-{uuid.uuid4().hex[:6].upper()}",
            journey_id    = journey_id,
            policy_number = policy.policy_number,
            customer_id   = customer.customer_id,
            reason        = reason_map[flag],
            priority      = priority,
            briefing_note = (
                f"Safety flag '{flag.value}' (confidence={confidence}) detected "
                f"for {customer.name} ({policy.policy_number}). "
                "Automated messaging paused. Human agent required."
            ),
        )

    trigger_phrases = []
    if flag != SafetyFlag.CLEAR:
        trigger_phrases = [random.choice(_MOCK_MESSAGES)]

    return SafetyResult(
        flag            = flag,
        confidence      = confidence,
        trigger_phrases = trigger_phrases,
        should_escalate = should_esc,
        escalation_case = esc_case,
        agent_note      = f"Mock safety check: {flag.value}",
    )


# ── Prompt ────────────────────────────────────────────────────────────────────

SAFETY_PROMPT = """\
You are a real-time safety monitor for Suraksha Life Insurance customer communications.

Analyse the following customer message for safety signals:

CUSTOMER: {name} | Age: {age} | Language: {language}
MESSAGE: {message}

Classify with ONE of these flags:
  clear | financial_stress | emotional_distress | crisis | mis_selling | vulnerable | bereavement

Return JSON:
{{
  "flag": "<flag>",
  "confidence": 0.0-1.0,
  "trigger_phrases": ["phrases that triggered this classification"],
  "agent_note": "brief explanation for human agent"
}}

Escalate to human if flag is crisis, mis_selling, or emotional_distress.
"""


# ── Agent ─────────────────────────────────────────────────────────────────────

class SafetyAgent:
    """Real-time distress & safety monitor."""

    def __init__(self):
        if not settings.mock_delivery:
            self._client = get_gemini_client()
        logger.info(f"SafetyAgent ready | mock={settings.mock_delivery}")

    def check(
        self,
        customer:   Customer,
        policy:     Policy | None = None,
        journey_id: str = "J-TEST",
        message:    str = "",
    ) -> SafetyResult:
        """Check a message (or random mock) for safety signals."""
        logger.debug(f"Safety check for {customer.name}")

        if settings.mock_delivery:
            # Fast keyword pre-check on message if provided
            if message:
                pre_flag = _keyword_precheck(message)
                if pre_flag != SafetyFlag.CLEAR:
                    result = SafetyResult(
                        flag            = pre_flag,
                        confidence      = 0.92,
                        trigger_phrases = [message[:80]],
                        should_escalate = pre_flag in (SafetyFlag.CRISIS, SafetyFlag.MIS_SELLING),
                        agent_note      = f"Keyword pre-check: {pre_flag.value}",
                    )
                    logger.warning(
                        f"Safety flag '{pre_flag.value}' | {customer.name} | confidence=0.92 | mock=True"
                    )
                    return result

            _pol = policy
            if _pol is None:
                from core.models import ProductType
                from datetime import date
                _pol = Policy(
                    policy_number="POL-STUB", product_type=ProductType.TERM,
                    annual_premium=0, sum_assured=0,
                    due_date=date.today(), payment_history=[],
                    years_completed=0, grace_period_days=30,
                )
            result = _mock_safety(customer, _pol, journey_id)
            log_fn = logger.warning if result.flag != SafetyFlag.CLEAR else logger.info
            log_fn(
                f"Safety → {customer.name} | flag={result.flag.value} | "
                f"confidence={result.confidence} | escalate={result.should_escalate} | mock=True"
            )
            return result

        # Real: keyword pre-check first (fast path)
        pre_flag = _keyword_precheck(message)
        if pre_flag == SafetyFlag.CRISIS:
            logger.critical(f"CRISIS signal detected for {customer.name} — keyword match")
            return SafetyResult(
                flag            = SafetyFlag.CRISIS,
                confidence      = 0.99,
                trigger_phrases = [message[:120]],
                should_escalate = True,
                escalation_case = EscalationCase(
                    case_id       = f"ESC-CRIS-{uuid.uuid4().hex[:6].upper()}",
                    journey_id    = journey_id,
                    policy_number = policy.policy_number if policy else "POL-UNKNOWN",
                    customer_id   = customer.customer_id,
                    reason        = EscalationReason.DISTRESS,
                    priority      = EscalationPriority.P1_URGENT,
                    briefing_note = f"CRISIS: {message[:200]}",
                ),
                agent_note      = "Immediate human intervention required.",
                is_safe         = False,
                distress_detected = True,
                severity        = "critical",
                action_required = "escalate_immediately",
            )

        # LLM check for subtle signals
        import json, re
        prompt = SAFETY_PROMPT.format(
            name     = customer.name,
            age      = customer.age,
            language = customer.preferred_language.value,
            message  = message,
        )
        response = self._client.models.generate_content(
            model    = settings.model_classify,
            contents = prompt,
        )
        raw = response.text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data    = json.loads(raw)
        # Support both old format (is_safe/distress_detected) and new (flag/confidence)
        if "flag" in data:
            flag    = SafetyFlag(data.get("flag", "clear"))
            conf    = float(data.get("confidence", 0.5))
        else:
            # Old-format JSON from test mocks
            is_safe = bool(data.get("is_safe", True))
            distress = bool(data.get("distress_detected", False))
            severity = data.get("severity", "low")
            if not is_safe:
                if severity == "critical" or distress:
                    flag = SafetyFlag.CRISIS if data.get("action_required") == "escalate_immediately" and severity == "critical" else SafetyFlag.EMOTIONAL_DISTRESS
                else:
                    flag = SafetyFlag.FINANCIAL_STRESS
            else:
                flag = SafetyFlag.CLEAR
            conf = 0.95 if not is_safe else 0.80
        should_esc = flag in (SafetyFlag.CRISIS, SafetyFlag.MIS_SELLING, SafetyFlag.EMOTIONAL_DISTRESS)
        esc_case   = None
        _pnum = policy.policy_number if policy else "POL-UNKNOWN"
        _cid  = customer.customer_id
        if should_esc:
            esc_case = EscalationCase(
                case_id       = f"ESC-SAF-{uuid.uuid4().hex[:6].upper()}",
                journey_id    = journey_id,
                policy_number = _pnum,
                customer_id   = _cid,
                reason        = EscalationReason.DISTRESS if flag != SafetyFlag.MIS_SELLING else EscalationReason.MIS_SELLING,
                priority      = EscalationPriority.P1_URGENT if flag == SafetyFlag.CRISIS else EscalationPriority.P2_HIGH,
                briefing_note = data.get("agent_note", ""),
            )
        result = SafetyResult(
            flag              = flag,
            confidence        = conf,
            trigger_phrases   = data.get("trigger_phrases", []),
            should_escalate   = should_esc,
            escalation_case   = esc_case,
            agent_note        = data.get("agent_note", ""),
            is_safe           = (flag == SafetyFlag.CLEAR),
            distress_detected = bool(data.get("distress_detected", flag in (
                SafetyFlag.EMOTIONAL_DISTRESS, SafetyFlag.CRISIS))),
            flags             = data.get("flags", data.get("trigger_phrases", [])),
            severity          = data.get("severity", "critical" if flag == SafetyFlag.CRISIS else
                                          "high" if flag == SafetyFlag.EMOTIONAL_DISTRESS else "low"),
            action_required   = data.get("action_required",
                                          "escalate_immediately" if should_esc else ""),
        )
        logger.info(f"Safety → {customer.name} | flag={flag.value} | confidence={conf}")
        return result
