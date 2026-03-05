"""
agents/layer3_quality/compliance_agent.py
───────────────────────────────────────────
IRDAI Compliance Agent

Checks all outbound messages against IRDAI (Insurance Regulatory and
Development Authority of India) communication guidelines:

  IRDAI Rules Checked:
  1. No guaranteed returns unless product actually guarantees them
  2. Must include policy number in renewal reminders
  3. Must mention lapse consequences clearly for lapse notices
  4. No false urgency / scare tactics
  5. Opt-out mechanism must be mentioned (STOP SMS/WhatsApp)
  6. Agent name / company name must be identifiable
  7. No misleading comparisons with competitors
  8. Premium amount must be accurate
  9. No pressure / coercive language
  10. Cooling-off period reminder for new policies (not applicable here)

Returns ComplianceResult with pass/fail per rule + overall verdict.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from loguru import logger
from google import genai

from core.config import settings
from core.models import Customer, Policy


# ── Result model ──────────────────────────────────────────────────────────────

@dataclass
class RuleCheck:
    rule_id:   str
    rule_name: str
    passed:    bool
    note:      str = ""


@dataclass
class ComplianceResult:
    # New-API required fields (made optional for backward compat)
    overall_pass:    bool           = True
    rules_checked:   int            = 0
    rules_failed:    int            = 0
    failed_rules:    list[RuleCheck] = field(default_factory=list)
    passed_rules:    list[RuleCheck] = field(default_factory=list)
    corrected_message: str | None   = None
    verdict:         str            = ""
    # Backward-compat fields used by tests
    rules_passed:    int            = 0
    violations:      list[str]      = field(default_factory=list)
    call_window_ok:  bool           = True
    disclosure_ok:   bool           = True
    opt_out_present: bool           = True
    irdai_compliant: bool           = True

    def __post_init__(self):
        # Sync: if old-API caller used irdai_compliant to indicate pass/fail
        if not self.irdai_compliant:
            self.overall_pass = False
        # Sync rules_passed ↔ rules_checked/rules_failed
        if self.rules_passed == 0 and self.rules_checked > 0:
            self.rules_passed = self.rules_checked - self.rules_failed
        # Sync violations → rules_failed
        if self.violations and self.rules_failed == 0:
            self.rules_failed = len(self.violations)
            if self.rules_checked == 0:
                self.rules_checked = self.rules_passed + self.rules_failed


# ── IRDAI rule definitions ─────────────────────────────────────────────────────

IRDAI_RULES = [
    ("R01", "No guaranteed returns unless policy guarantees them"),
    ("R02", "Policy number included in renewal communication"),
    ("R03", "Lapse consequences clearly stated in lapse notices"),
    ("R04", "No false urgency or scare tactics"),
    ("R05", "Opt-out instructions present (STOP)"),
    ("R06", "Company/insurer name identifiable"),
    ("R07", "No misleading competitor comparisons"),
    ("R08", "Premium amount accurate and clearly stated"),
    ("R09", "No coercive or pressure language"),
]

# Red-flag phrases (fast pre-scan)
_BANNED_PHRASES = [
    "guaranteed returns", "100% returns", "double your money",
    "act now or lose everything", "last chance ever",
    "better than LIC", "worse than", "competitor",
    "you must pay", "we will cancel your life cover immediately",
]


def _fast_rule_check(message: str, policy: Policy) -> list[RuleCheck]:
    """Fast deterministic checks (no LLM needed)."""
    msg_lower = message.lower()
    results   = []

    # R02 — policy number present
    results.append(RuleCheck(
        rule_id  = "R02",
        rule_name= "Policy number included",
        passed   = policy.policy_number.lower() in msg_lower,
        note     = "" if policy.policy_number.lower() in msg_lower else "Policy number missing from message",
    ))

    # R05 — opt-out
    has_stop = any(x in msg_lower for x in ["stop", "opt out", "unsubscribe", "nahi chahiye"])
    results.append(RuleCheck(
        rule_id  = "R05",
        rule_name= "Opt-out instructions present",
        passed   = has_stop,
        note     = "" if has_stop else "No STOP/opt-out instructions found",
    ))

    # R06 — company name
    has_company = any(x in msg_lower for x in ["suraksha", "insurance", "bima"])
    results.append(RuleCheck(
        rule_id  = "R06",
        rule_name= "Company name identifiable",
        passed   = has_company,
        note     = "" if has_company else "Company/insurer name not mentioned",
    ))

    # R01 / R07 / R09 — banned phrases
    found_banned = [p for p in _BANNED_PHRASES if p in msg_lower]
    results.append(RuleCheck(
        rule_id  = "R01",
        rule_name= "No guaranteed returns claim",
        passed   = not any(p in msg_lower for p in ["guaranteed returns", "100% returns", "double your money"]),
        note     = f"Banned phrase found: {found_banned[0]}" if found_banned else "",
    ))
    results.append(RuleCheck(
        rule_id  = "R07",
        rule_name= "No competitor comparisons",
        passed   = not any(p in msg_lower for p in ["better than lic", "worse than", "competitor"]),
        note     = "",
    ))
    results.append(RuleCheck(
        rule_id  = "R09",
        rule_name= "No coercive language",
        passed   = not any(p in msg_lower for p in ["you must pay", "we will cancel your life cover immediately"]),
        note     = "",
    ))

    return results


# ── Mock helpers ───────────────────────────────────────────────────────────────

def _mock_compliance(customer: Customer, policy: Policy, message: str) -> ComplianceResult:
    fast_checks = _fast_rule_check(message, policy)

    # Add mock LLM-style checks for remaining rules
    remaining = [
        RuleCheck("R03", "Lapse consequences stated",     random.random() > 0.15, ""),
        RuleCheck("R04", "No false urgency",               random.random() > 0.10, ""),
        RuleCheck("R08", "Premium amount accurate",        random.random() > 0.05, ""),
    ]
    all_checks = fast_checks + remaining

    failed = [r for r in all_checks if not r.passed]
    passed = [r for r in all_checks if r.passed]

    overall = len(failed) == 0
    corrected = None
    if not overall:
        corrected = (
            f"[COMPLIANT VERSION]\n{message}\n\n"
            f"STOP karne ke liye reply karein STOP | "
            f"Suraksha Life Insurance | Policy: {policy.policy_number}"
        )

    return ComplianceResult(
        overall_pass     = overall,
        rules_checked    = len(all_checks),
        rules_failed     = len(failed),
        failed_rules     = failed,
        passed_rules     = passed,
        corrected_message= corrected,
        verdict          = (
            "Message is IRDAI-compliant." if overall
            else f"{len(failed)} compliance issue(s) found. Corrected version generated."
        ),
    )


# ── Prompt ────────────────────────────────────────────────────────────────────

COMPLIANCE_PROMPT = """\
You are an IRDAI compliance checker for Suraksha Life Insurance.

Review the following message against IRDAI communication guidelines and check:
R03: Are lapse consequences clearly stated?
R04: Is there false urgency or scare tactics?
R08: Is the premium amount ₹{premium:,} mentioned accurately?

MESSAGE:
{message}

Return JSON:
{{
  "R03": {{"passed": true/false, "note": ""}},
  "R04": {{"passed": true/false, "note": ""}},
  "R08": {{"passed": true/false, "note": ""}}
}}
"""


# ── Agent ─────────────────────────────────────────────────────────────────────

class ComplianceAgent:
    """IRDAI compliance checker for all outbound messages."""

    def __init__(self):
        if not settings.mock_delivery:
            self._client = genai.Client(api_key=settings.gemini_api_key)
        logger.info(f"ComplianceAgent ready | mock={settings.mock_delivery}")

    def check(
        self,
        customer: Customer,
        policy:   Policy,
        message:  str,
        channel:  str = "whatsapp",
    ) -> ComplianceResult:
        """Check message for IRDAI compliance. Returns ComplianceResult."""
        logger.debug(f"Compliance check for {customer.name} / {channel}")

        if settings.mock_delivery:
            result = _mock_compliance(customer, policy, message)
            log_fn = logger.warning if not result.overall_pass else logger.info
            log_fn(
                f"Compliance → {customer.name} | pass={result.overall_pass} | "
                f"failed={result.rules_failed}/{result.rules_checked} | mock=True"
            )
            return result

        # Real: fast deterministic checks + LLM for nuanced rules
        fast_checks = _fast_rule_check(message, policy)

        import json, re
        prompt = COMPLIANCE_PROMPT.format(
            premium = int(policy.annual_premium),
            message = message,
        )
        response = self._client.models.generate_content(
            model    = settings.model_classify,
            contents = prompt,
        )
        raw = response.text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        llm_data = json.loads(raw)

        llm_checks = []
        for rule_id, info in llm_data.items():
            rule_names = {"R03": "Lapse consequences stated", "R04": "No false urgency", "R08": "Premium accurate"}
            llm_checks.append(RuleCheck(
                rule_id  = rule_id,
                rule_name= rule_names.get(rule_id, rule_id),
                passed   = bool(info.get("passed", True)),
                note     = info.get("note", ""),
            ))

        all_checks = fast_checks + llm_checks
        failed     = [r for r in all_checks if not r.passed]
        passed     = [r for r in all_checks if r.passed]
        overall    = len(failed) == 0
        corrected  = None
        if not overall:
            corrected = (
                f"{message}\n\nSTOP karne ke liye reply karein STOP | "
                f"Suraksha Life Insurance | Policy: {policy.policy_number}"
            )

        result = ComplianceResult(
            overall_pass     = overall,
            rules_checked    = len(all_checks),
            rules_failed     = len(failed),
            failed_rules     = failed,
            passed_rules     = passed,
            corrected_message= corrected,
            verdict          = "IRDAI-compliant." if overall else f"{len(failed)} issue(s) found.",
        )
        logger.info(f"Compliance → {customer.name} | pass={overall} | failed={len(failed)}")
        return result

    # ── Backward-compat alias used by the test suite ─────────────────────────

    def _mock_check(
        self, message: str, channel: str, customer: Customer,
    ) -> ComplianceResult:
        """Alias: run compliance in mock mode with minimal inputs."""
        from core.models import Policy, PolicyStatus, ProductType
        from datetime import date
        stub_policy = Policy(
            policy_number    = "POL-MOCK",
            customer_id      = customer.customer_id,
            product_type     = ProductType.TERM,
            product_name     = "Mock Policy",
            sum_assured      = 1_000_000,
            annual_premium   = 25_000,
            policy_start_date= date.today(),
            renewal_due_date = date.today(),
            tenure_years     = 10,
            years_completed  = 1,
        )
        return _mock_compliance(customer, stub_policy, message)
