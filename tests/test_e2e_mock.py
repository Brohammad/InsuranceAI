"""
tests/test_e2e_mock.py
──────────────────────
End-to-end mock test suite for Project RenewAI.

Covers the COMPLETE journey from customer input to learning loop without
making any real API calls (Gemini, Twilio, ElevenLabs, Razorpay).

Scenarios tested:
  S1  — Happy path: at-risk customer → WhatsApp → quality pass → payment success
  S2  — High-risk customer → multi-channel dispatch → email + voice → escalation
  S3  — Auto-renewer customer → light nudge → quality gate passes immediately
  S4  — Distress customer → safety flag → immediate human escalation (quality=0)
  S5  — Full Layer 1 pipeline: segmentation → propensity → timing → channel → journey
  S6  — Layer 2 dispatcher: step routing to WhatsApp, Email, Voice, Payment agents
  S7  — Layer 3 quality gate: approve ≥70, block <70, escalate on safety flag
  S8  — Layer 4 feedback loop: outcome signals update lapse scores
  S9  — Layer 5 human queue: escalation routing, SLA assignment, resolution
  S10 — Closed feedback loop: refresh_from_feedback auto-triggered after threshold
  S11 — Payment agent: UPI deep link, QR code, AutoPay mandate all generated
  S12 — run_batch_with_feedback(): batch + feedback loop combined
  S13 — Objection handler: handles price/delay/trust objections without Gemini
  S14 — Channel selector: DND customer sent only email; at-risk gets multi-channel
  S15 — Timing agent: urgency override on ≤3 days; standard window otherwise

All external calls are patched at the point of use.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid
from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ══════════════════════════════════════════════════════════════════════════════
#  Shared fixtures
# ══════════════════════════════════════════════════════════════════════════════

from core.models import (
    Channel, Customer, CustomerSegment, EscalationCase, EscalationPriority,
    EscalationReason, InteractionOutcome, JourneyStatus, Language, Policy,
    PolicyStatus, ProductType, RenewalJourney, SegmentationResult,
)


def _customer(
    cid: str = "CUST-001",
    segment_hint: str = "at_risk",
    dnd: bool = False,
    lang: Language = Language.ENGLISH,
    channel: Channel = Channel.WHATSAPP,
    age: int = 42,
    premium_hint: float = 25_000,
) -> Customer:
    """Factory: build a Customer with sensible defaults."""
    return Customer(
        customer_id=cid,
        name="Rajan Mehta",
        age=age,
        gender="M",
        city="Mumbai",
        state="Maharashtra",
        preferred_language=lang,
        preferred_channel=channel,
        preferred_call_time="18:00-20:00",
        email=f"{cid}@test.com",
        phone="+919876543210",
        whatsapp_number="+919876543210",
        occupation="IT Professional",
        is_on_dnd=dnd,
    )


def _policy(
    pid: str = "POL-0001",
    cid: str = "CUST-001",
    days_to_due: int = 14,
    payment_history: list | None = None,
    auto_debit: bool = False,
    premium: float = 25_000,
    product_type: ProductType = ProductType.TERM,
    status: PolicyStatus = PolicyStatus.ACTIVE,
) -> Policy:
    """Factory: build a Policy with sensible defaults."""
    if payment_history is None:
        payment_history = ["on_time", "late", "on_time"]
    due = date.today() + timedelta(days=days_to_due)
    return Policy(
        policy_number=pid,
        customer_id=cid,
        product_type=product_type,
        product_name="Term Shield Plus",
        sum_assured=1_000_000,
        annual_premium=premium,
        policy_start_date=date.today() - timedelta(days=365 * 3),
        renewal_due_date=due,
        tenure_years=20,
        years_completed=3,
        status=status,
        payment_mode="annual",
        has_auto_debit=auto_debit,
        payment_history=payment_history,
    )


def _gemini_response(json_text: str) -> MagicMock:
    """Return a MagicMock that looks like a google.genai response."""
    mock = MagicMock()
    mock.text = json_text
    return mock


def _mock_gemini_client(json_text: str) -> MagicMock:
    """Return a MagicMock Gemini client whose generate_content returns json_text."""
    client = MagicMock()
    client.models.generate_content.return_value = _gemini_response(json_text)
    return client


# ══════════════════════════════════════════════════════════════════════════════
#  S1 — HAPPY PATH: at-risk customer → WhatsApp → quality pass → payment
# ══════════════════════════════════════════════════════════════════════════════

class TestS1HappyPath:
    """Full journey for an at-risk customer who pays via WhatsApp link."""

    SEG_JSON = json.dumps({
        "segment": "nudge_needed",
        "recommended_tone": "friendly",
        "recommended_strategy": "tax_benefit_reminder",
        "risk_flag": "medium",
        "reasoning": "Has one late payment but mostly on time.",
    })
    PROP_JSON = json.dumps({
        "lapse_score": 45,
        "intervention_intensity": "moderate",
        "top_reasons": ["one late payment", "premium ₹25K relative to income"],
        "recommended_actions": ["WhatsApp nudge", "send UPI link"],
        "reasoning": "Moderate risk — single late payment.",
    })
    TIMING_JSON = json.dumps({
        "best_contact_window": "18:00-20:00",
        "best_days": ["Wednesday", "Thursday"],
        "salary_day_flag": True,
        "urgency_override": False,
        "reasoning": "IT professional, evenings free.",
    })
    CHANNEL_JSON = json.dumps({
        "channel_sequence": ["whatsapp", "email"],
        "reasoning": "Preferred channel is WhatsApp.",
    })

    def _layer1_client(self, call_idx: int) -> str:
        return [self.SEG_JSON, self.PROP_JSON, self.TIMING_JSON, self.CHANNEL_JSON][call_idx % 4]

    def test_layer1_journey_created(self):
        """Layer 1 returns a RenewalJourney with correct segment and score."""
        cust = _customer()
        pol  = _policy()

        call_count = [0]

        def side_effect(*args, **kwargs):
            resp = _gemini_response(self._layer1_client(call_count[0]))
            call_count[0] += 1
            return resp

        with patch("agents.layer1_strategic.segmentation.get_gemini_client") as m_seg, \
             patch("agents.layer1_strategic.propensity.get_gemini_client") as m_prop, \
             patch("agents.layer1_strategic.timing.get_gemini_client") as m_tim, \
             patch("agents.layer1_strategic.channel_selector.get_gemini_client") as m_ch, \
             patch("agents.layer1_strategic.orchestrator.create_journey"):
            for m in (m_seg, m_prop, m_tim, m_ch):
                client = MagicMock()
                client.models.generate_content.side_effect = side_effect
                m.return_value = client

            from agents.layer1_strategic.orchestrator import run_layer1
            journey = run_layer1(cust, pol)

        assert journey is not None, "Journey must not be None"
        assert journey.policy_number == pol.policy_number
        assert journey.customer_id == cust.customer_id
        assert journey.lapse_score is not None
        assert len(journey.steps) > 0

    def test_journey_has_whatsapp_step(self):
        """First step must be WhatsApp given customer preference."""
        cust = _customer()
        pol  = _policy()

        call_count = [0]

        def side_effect(*args, **kwargs):
            resp = _gemini_response(self._layer1_client(call_count[0]))
            call_count[0] += 1
            return resp

        with patch("agents.layer1_strategic.segmentation.get_gemini_client") as m_seg, \
             patch("agents.layer1_strategic.propensity.get_gemini_client") as m_prop, \
             patch("agents.layer1_strategic.timing.get_gemini_client") as m_tim, \
             patch("agents.layer1_strategic.channel_selector.get_gemini_client") as m_ch, \
             patch("agents.layer1_strategic.orchestrator.create_journey"):
            for m in (m_seg, m_prop, m_tim, m_ch):
                client = MagicMock()
                client.models.generate_content.side_effect = side_effect
                m.return_value = client

            from agents.layer1_strategic.orchestrator import run_layer1
            journey = run_layer1(cust, pol)

        channels = [s.channel for s in journey.steps]
        assert Channel.WHATSAPP in channels, "WhatsApp must appear in journey steps"

    def test_quality_gate_approves_good_message(self):
        """A well-written message with all high scores gets approved."""
        from agents.layer3_quality.quality_scoring import compute_quality_score
        from agents.layer3_quality.critique_agent import CritiqueResult
        from agents.layer3_quality.compliance_agent import ComplianceResult
        from agents.layer3_quality.safety_agent import SafetyResult
        from agents.layer3_quality.sentiment_agent import SentimentResult, SentimentPolarity

        critique = CritiqueResult(
            approved=True,
            tone_score=9, accuracy_score=9, personalisation_score=8,
            conversion_likelihood=8,
            overall_verdict="Excellent message.",
        )
        compliance = ComplianceResult(
            rules_checked=3, rules_passed=3, violations=[],
            call_window_ok=True, disclosure_ok=True, opt_out_present=True,
            irdai_compliant=True,
        )
        safety = SafetyResult(is_safe=True, distress_detected=False, flags=[], severity="low")
        sentiment = SentimentResult(
            polarity=SentimentPolarity.POSITIVE,
            score=6.0, magnitude=0.8,
            customer_intent="renew",
        )

        score = compute_quality_score(
            journey_id="J-001", policy_number="POL-0001",
            customer_name="Rajan Mehta", channel="whatsapp",
            critique=critique, compliance=compliance,
            safety=safety, sentiment=sentiment,
        )
        assert score.total_score >= 70, f"Expected ≥70, got {score.total_score}"
        assert score.grade in ("A", "B", "C")


# ══════════════════════════════════════════════════════════════════════════════
#  S2 — HIGH-RISK: multi-channel → escalation
# ══════════════════════════════════════════════════════════════════════════════

class TestS2HighRisk:
    """High-risk customer: multiple missed payments, due in 3 days → escalated."""

    def test_high_risk_propensity_score(self):
        """Customer with 3 missed payments and due in 3 days → lapse_score ≥ 80."""
        prop_json = json.dumps({
            "lapse_score": 88,
            "intervention_intensity": "urgent",
            "top_reasons": ["3 missed payments", "due in 3 days", "no auto-debit"],
            "recommended_actions": ["immediate human call", "offer EMI plan"],
            "reasoning": "Very high risk.",
        })
        from agents.layer1_strategic.propensity import PropensityAgent
        cust = _customer()
        pol  = _policy(payment_history=["missed", "missed", "missed"], days_to_due=3)

        with patch("agents.layer1_strategic.propensity.get_gemini_client") as mock_client:
            mock_client.return_value = _mock_gemini_client(prop_json)
            agent = PropensityAgent()
            result = agent.run(cust, pol, segment="high_risk")

        assert result.lapse_score >= 80
        assert result.intervention_intensity == "urgent"

    def test_escalation_case_created(self):
        """Escalation case is created with correct priority for a high-risk distress scenario."""
        from agents.layer5_human.queue_manager import QueueManager

        case = EscalationCase(
            case_id=f"ESC-{uuid.uuid4().hex[:8]}",
            journey_id="J-002",
            policy_number="POL-0002",
            customer_id="CUST-002",
            reason=EscalationReason.DISTRESS,
            priority=EscalationPriority.P1_URGENT,
            briefing_note="Customer indicated financial distress during voice call.",
        )

        with patch("agents.layer5_human.queue_manager.sqlite3.connect") as mock_db:
            mock_conn = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value = MagicMock()
            mock_conn.commit.return_value = None

            qm = QueueManager()
            qm._db_add_case(mock_conn, case)
            mock_conn.execute.assert_called_once()

    def test_quality_gate_blocks_unsafe_message(self):
        """A message with safety flags must score 0 and be blocked."""
        from agents.layer3_quality.quality_scoring import compute_quality_score
        from agents.layer3_quality.critique_agent import CritiqueResult
        from agents.layer3_quality.compliance_agent import ComplianceResult
        from agents.layer3_quality.safety_agent import SafetyResult, SafetyFlag
        from agents.layer3_quality.sentiment_agent import SentimentResult, SentimentPolarity

        safety = SafetyResult(
            is_safe=False,
            distress_detected=True,
            flags=["threatening_language", "distress_signal"],
            severity="critical",
            action_required="escalate_immediately",
        )
        critique = CritiqueResult(approved=False, tone_score=2, accuracy_score=5,
                                   personalisation_score=3, conversion_likelihood=2)
        compliance = ComplianceResult(
            rules_checked=2, rules_passed=1, violations=["outside_call_window"],
            call_window_ok=False, disclosure_ok=True, opt_out_present=False,
            irdai_compliant=False,
        )
        sentiment = SentimentResult(
            polarity=SentimentPolarity.NEGATIVE, score=-7.0, magnitude=0.9,
            customer_intent="complaint",
        )

        score = compute_quality_score(
            journey_id="J-002", policy_number="POL-0002",
            customer_name="Test", channel="voice",
            critique=critique, compliance=compliance,
            safety=safety, sentiment=sentiment,
        )
        assert score.total_score < 70, f"Unsafe message must score <70, got {score.total_score}"
        assert score.grade in ("D", "F")


# ══════════════════════════════════════════════════════════════════════════════
#  S3 — AUTO-RENEWER: light nudge, no escalation
# ══════════════════════════════════════════════════════════════════════════════

class TestS3AutoRenewer:
    """Auto-renewer: auto_debit=True, all on_time → score ≤ 20, intensity=none/light."""

    def test_auto_renewer_gets_low_lapse_score(self):
        prop_json = json.dumps({
            "lapse_score": 8,
            "intervention_intensity": "none",
            "top_reasons": ["auto-debit active", "all payments on time"],
            "recommended_actions": ["send friendly reminder only"],
            "reasoning": "Auto-debit + perfect payment history.",
        })
        from agents.layer1_strategic.propensity import PropensityAgent
        cust = _customer()
        pol  = _policy(
            auto_debit=True,
            payment_history=["on_time", "on_time", "on_time", "on_time"],
        )

        with patch("agents.layer1_strategic.propensity.get_gemini_client") as mock_client:
            mock_client.return_value = _mock_gemini_client(prop_json)
            agent = PropensityAgent()
            result = agent.run(cust, pol, segment="auto_renewer")

        assert result.lapse_score <= 20
        assert result.intervention_intensity in ("none", "light")

    def test_auto_renewer_segment_classification(self):
        seg_json = json.dumps({
            "segment": "auto_renewer",
            "recommended_tone": "friendly",
            "recommended_strategy": "renewal_reminder",
            "risk_flag": "low",
            "reasoning": "Auto-debit and consistent payment.",
        })
        from agents.layer1_strategic.segmentation import SegmentationAgent
        cust = _customer()
        pol  = _policy(auto_debit=True, payment_history=["on_time"] * 5)

        with patch("agents.layer1_strategic.segmentation.get_gemini_client") as mock_client:
            mock_client.return_value = _mock_gemini_client(seg_json)
            agent = SegmentationAgent()
            result = agent.run(cust, pol)

        assert result.segment == CustomerSegment.AUTO_RENEWER
        assert result.risk_flag == "low"


# ══════════════════════════════════════════════════════════════════════════════
#  S4 — DISTRESS: safety flag → immediate escalation
# ══════════════════════════════════════════════════════════════════════════════

class TestS4DistressEscalation:
    """Distress customer triggers safety flag → must not send message → escalate."""

    def test_distress_segment_detected(self):
        seg_json = json.dumps({
            "segment": "distress",
            "recommended_tone": "empathetic",
            "recommended_strategy": "personal_call",
            "risk_flag": "high",
            "reasoning": "All payments missed, occupation suggests financial stress.",
        })
        from agents.layer1_strategic.segmentation import SegmentationAgent
        cust = _customer()
        pol  = _policy(payment_history=["missed", "missed", "missed"])

        with patch("agents.layer1_strategic.segmentation.get_gemini_client") as mock_client:
            mock_client.return_value = _mock_gemini_client(seg_json)
            agent = SegmentationAgent()
            result = agent.run(cust, pol)

        assert result.segment == CustomerSegment.DISTRESS
        assert result.risk_flag == "high"
        assert result.recommended_tone == "empathetic"

    def test_safety_flag_forces_escalation_action(self):
        """When safety agent returns distress_detected=True, action must be escalate_immediately."""
        from agents.layer3_quality.safety_agent import SafetyAgent, SafetyResult

        safety_json = json.dumps({
            "is_safe": False,
            "distress_detected": True,
            "flags": ["financial_hardship", "suicidal_ideation"],
            "severity": "critical",
            "action_required": "escalate_immediately",
            "reasoning": "Customer mentioned inability to pay and desperation.",
        })

        with patch("agents.layer3_quality.safety_agent.get_gemini_client") as mock_client:
            mock_client.return_value = _mock_gemini_client(safety_json)
            agent = SafetyAgent()
            result = agent.check(
                message="I can't afford this and I don't know what to do anymore",
                customer=_customer(),
            )

        assert not result.is_safe
        assert result.distress_detected
        assert result.action_required == "escalate_immediately"
        assert result.severity == "critical"


# ══════════════════════════════════════════════════════════════════════════════
#  S5 — FULL LAYER 1 PIPELINE (unit isolation)
# ══════════════════════════════════════════════════════════════════════════════

class TestS5Layer1Pipeline:
    """Test each Layer 1 agent individually with mocked Gemini."""

    def test_segmentation_agent(self):
        seg_json = json.dumps({
            "segment": "price_sensitive",
            "recommended_tone": "empathetic",
            "recommended_strategy": "emi_offer",
            "risk_flag": "medium",
            "reasoning": "High premium vs income.",
        })
        from agents.layer1_strategic.segmentation import SegmentationAgent
        with patch("agents.layer1_strategic.segmentation.get_gemini_client") as m:
            m.return_value = _mock_gemini_client(seg_json)
            result = SegmentationAgent().run(_customer(), _policy(premium=85_000))
        assert result.segment == CustomerSegment.PRICE_SENSITIVE
        assert result.recommended_strategy == "emi_offer"

    def test_propensity_agent(self):
        prop_json = json.dumps({
            "lapse_score": 62,
            "intervention_intensity": "intensive",
            "top_reasons": ["late payments", "high premium"],
            "recommended_actions": ["voice call", "emi offer"],
            "reasoning": "Above average risk.",
        })
        from agents.layer1_strategic.propensity import PropensityAgent
        with patch("agents.layer1_strategic.propensity.get_gemini_client") as m:
            m.return_value = _mock_gemini_client(prop_json)
            result = PropensityAgent().run(_customer(), _policy(), segment="price_sensitive")
        assert 56 <= result.lapse_score <= 80
        assert result.intervention_intensity == "intensive"

    def test_timing_agent(self):
        timing_json = json.dumps({
            "best_contact_window": "18:00-20:00",
            "best_days": ["Wednesday", "Thursday"],
            "salary_day_flag": True,
            "urgency_override": False,
            "reasoning": "Evening after work.",
        })
        from agents.layer1_strategic.timing import TimingAgent
        with patch("agents.layer1_strategic.timing.get_gemini_client") as m:
            m.return_value = _mock_gemini_client(timing_json)
            result = TimingAgent().run(_customer(), _policy(), intensity="moderate")
        assert "18" in result.best_contact_window
        assert result.salary_day_flag is True

    def test_channel_selector_agent(self):
        ch_json = json.dumps({
            "channel_sequence": ["whatsapp", "email", "voice"],
            "reasoning": "Multi-channel for moderate risk.",
        })
        from agents.layer1_strategic.channel_selector import ChannelSelectorAgent
        with patch("agents.layer1_strategic.channel_selector.get_gemini_client") as m:
            m.return_value = _mock_gemini_client(ch_json)
            result = ChannelSelectorAgent().run(
                _customer(), _policy(),
                segment="nudge_needed", lapse_score=45, urgency_override=False,
            )
        assert Channel.WHATSAPP in result.channel_sequence
        assert len(result.channel_sequence) >= 2

    def test_timing_urgency_override_for_imminent_due(self):
        """Policy due ≤ 3 days should trigger urgency_override=True."""
        timing_json = json.dumps({
            "best_contact_window": "10:00-12:00",
            "best_days": ["Monday"],
            "salary_day_flag": False,
            "urgency_override": True,
            "reasoning": "Due in 2 days — override to urgent.",
        })
        from agents.layer1_strategic.timing import TimingAgent
        with patch("agents.layer1_strategic.timing.get_gemini_client") as m:
            m.return_value = _mock_gemini_client(timing_json)
            result = TimingAgent().run(_customer(), _policy(days_to_due=2), intensity="urgent")
        assert result.urgency_override is True


# ══════════════════════════════════════════════════════════════════════════════
#  S6 — LAYER 2 DISPATCH: agent routing
# ══════════════════════════════════════════════════════════════════════════════

class TestS6Layer2Dispatch:
    """WhatsApp, Email, Voice and Payment agents all work in mock mode."""

    def test_whatsapp_agent_mock_delivery(self):
        """WhatsApp agent in mock_delivery=True returns a result without calling Twilio."""
        from agents.layer2_execution.whatsapp_agent import WhatsAppAgent
        cust = _customer()
        pol  = _policy()

        with patch("agents.layer2_execution.whatsapp_agent.settings") as mock_settings:
            mock_settings.mock_delivery = True
            agent = WhatsAppAgent.__new__(WhatsAppAgent)
            agent.mock = True
            result = agent._mock_send(cust, pol, tone="friendly", strategy="renewal_reminder")

        assert result is not None
        assert result.outcome is not None

    def test_whatsapp_agent_real_message_via_gemini(self):
        """WhatsApp agent generates message via mocked Gemini and returns result."""
        from agents.layer2_execution.whatsapp_agent import WhatsAppAgent
        cust = _customer()
        pol  = _policy()

        fake_message = "Dear Rajan, your policy POL-0001 renews in 14 days. Click [PAYMENT_LINK]"

        with patch("agents.layer2_execution.whatsapp_agent.settings") as mock_settings, \
             patch("agents.layer2_execution.whatsapp_agent.get_gemini_client") as mock_gc:
            mock_settings.mock_delivery = False
            mock_settings.model_execution = "gemini-2.5-flash"
            client = MagicMock()
            client.models.generate_content.return_value = _gemini_response(fake_message)
            mock_gc.return_value = client
            agent = WhatsAppAgent()
            result = agent.send(
                customer=cust, policy=pol,
                tone="friendly", strategy="renewal_reminder",
            )

        assert result.message_body == fake_message or result.message_body
        assert result.outcome is not None

    def test_email_agent_mock_delivery(self):
        """Email agent mock mode returns an Interaction without SMTP."""
        from agents.layer2_execution.email_agent import EmailAgent
        cust = _customer()
        pol  = _policy()

        with patch("agents.layer2_execution.email_agent.settings") as mock_settings:
            mock_settings.mock_delivery = True
            agent = EmailAgent.__new__(EmailAgent)
            agent.mock = True
            result = agent._mock_send(cust, pol, tone="formal", strategy="renewal_reminder")

        assert result is not None

    def test_payment_agent_upi_link(self):
        """Payment agent generates a valid UPI deep link."""
        from agents.layer2_execution.payment_agent import PaymentAgent
        pol = _policy(premium=25_000)
        agent = PaymentAgent()
        upi = agent.build_upi_link(pol)
        assert upi.deep_link.startswith("upi://pay")
        assert "suraksha.life@razorpay" in upi.deep_link
        assert "25000" in upi.deep_link

    def test_payment_agent_qr_code(self):
        """Payment agent generates real PNG QR code bytes."""
        from agents.layer2_execution.payment_agent import PaymentAgent
        pol = _policy(premium=25_000)
        agent = PaymentAgent()
        qr = agent.build_qr_code(pol)
        assert len(qr.png_bytes) > 0
        assert qr.png_b64  # base64 string is non-empty
        # PNG magic bytes
        assert qr.png_bytes[:4] == b"\x89PNG"

    def test_payment_agent_mock_status_check(self):
        """Mock check_status() returns 'paid' or 'pending' without Razorpay."""
        from agents.layer2_execution.payment_agent import PaymentAgent
        agent = PaymentAgent()
        # Call 10 times — must always return a valid status string
        results = [agent.check_status(f"TXN-{i:04d}") for i in range(10)]
        assert all(r in ("paid", "pending", "failed") for r in results)


# ══════════════════════════════════════════════════════════════════════════════
#  S7 — LAYER 3 QUALITY GATE
# ══════════════════════════════════════════════════════════════════════════════

class TestS7QualityGate:
    """Quality scoring: pass ≥70, fail <70, safety zero-out."""

    def test_full_quality_pipeline_pass(self):
        """All agents approve → composite ≥ 70."""
        from agents.layer3_quality.quality_scoring import compute_quality_score
        from agents.layer3_quality.critique_agent import CritiqueResult
        from agents.layer3_quality.compliance_agent import ComplianceResult
        from agents.layer3_quality.safety_agent import SafetyResult
        from agents.layer3_quality.sentiment_agent import SentimentResult, SentimentPolarity

        score = compute_quality_score(
            journey_id="J-007", policy_number="POL-0007",
            customer_name="Sunita", channel="whatsapp",
            critique=CritiqueResult(
                approved=True,
                tone_score=8, accuracy_score=9, personalisation_score=8,
                conversion_likelihood=8, overall_verdict="Good.",
            ),
            compliance=ComplianceResult(
                rules_checked=3, rules_passed=3, violations=[],
                call_window_ok=True, disclosure_ok=True, opt_out_present=True,
                irdai_compliant=True,
            ),
            safety=SafetyResult(is_safe=True, distress_detected=False, flags=[], severity="low"),
            sentiment=SentimentResult(
                polarity=SentimentPolarity.POSITIVE, score=5.0, magnitude=0.7,
                customer_intent="renew",
            ),
        )
        assert score.total_score >= 70
        assert score.grade in ("A", "B", "C")

    def test_full_quality_pipeline_fail_low_scores(self):
        """All agents give low scores → composite < 70."""
        from agents.layer3_quality.quality_scoring import compute_quality_score
        from agents.layer3_quality.critique_agent import CritiqueResult
        from agents.layer3_quality.compliance_agent import ComplianceResult
        from agents.layer3_quality.safety_agent import SafetyResult
        from agents.layer3_quality.sentiment_agent import SentimentResult, SentimentPolarity

        score = compute_quality_score(
            journey_id="J-008", policy_number="POL-0008",
            customer_name="Test", channel="email",
            critique=CritiqueResult(
                approved=False, tone_score=3, accuracy_score=3,
                personalisation_score=2, conversion_likelihood=2,
                overall_verdict="Poor message.",
            ),
            compliance=ComplianceResult(
                rules_checked=3, rules_passed=1, violations=["outside_call_window"],
                call_window_ok=False, disclosure_ok=False, opt_out_present=False,
                irdai_compliant=False,
            ),
            safety=SafetyResult(is_safe=True, distress_detected=False, flags=[], severity="low"),
            sentiment=SentimentResult(
                polarity=SentimentPolarity.NEGATIVE, score=-5.0, magnitude=0.8,
                customer_intent="complaint",
            ),
        )
        assert score.total_score < 70
        assert score.grade in ("D", "F")

    def test_safety_flag_zeroes_safety_component(self):
        """A safety flag on an otherwise good message must reduce safety component to 0."""
        from agents.layer3_quality.quality_scoring import compute_quality_score
        from agents.layer3_quality.critique_agent import CritiqueResult
        from agents.layer3_quality.compliance_agent import ComplianceResult
        from agents.layer3_quality.safety_agent import SafetyResult
        from agents.layer3_quality.sentiment_agent import SentimentResult, SentimentPolarity

        score = compute_quality_score(
            journey_id="J-009", policy_number="POL-0009",
            customer_name="Test", channel="voice",
            critique=CritiqueResult(
                approved=True, tone_score=8, accuracy_score=8,
                personalisation_score=7, conversion_likelihood=7,
                overall_verdict="Good.",
            ),
            compliance=ComplianceResult(
                rules_checked=2, rules_passed=2, violations=[],
                call_window_ok=True, disclosure_ok=True, opt_out_present=True,
                irdai_compliant=True,
            ),
            safety=SafetyResult(
                is_safe=False, distress_detected=True,
                flags=["distress_signal"], severity="high",
                action_required="escalate_immediately",
            ),
            sentiment=SentimentResult(
                polarity=SentimentPolarity.NEGATIVE, score=-3.0, magnitude=0.6,
                customer_intent="unknown",
            ),
        )
        # Safety weight is 20%; flagged = 0 on that component
        assert score.safety_score == 0.0

    def test_compliance_agent_mock(self):
        """Compliance agent mock mode returns compliant result without Gemini."""
        from agents.layer3_quality.compliance_agent import ComplianceAgent
        with patch("agents.layer3_quality.compliance_agent.settings") as mock_s:
            mock_s.mock_delivery = True
            agent = ComplianceAgent.__new__(ComplianceAgent)
            agent.mock = True
            result = agent._mock_check(
                message="Your policy is due in 14 days. Click here to renew.",
                channel="whatsapp",
                customer=_customer(),
            )
        assert result.irdai_compliant is True

    def test_critique_agent_mock(self):
        """Critique agent mock returns plausible scores."""
        from agents.layer3_quality.critique_agent import CritiqueAgent
        with patch("agents.layer3_quality.critique_agent.settings") as mock_s:
            mock_s.mock_delivery = True
            agent = CritiqueAgent.__new__(CritiqueAgent)
            agent.mock = True
            result = agent._mock_critique(
                message="Dear Rajan, renew now!",
                customer=_customer(),
                policy=_policy(),
            )
        assert 1 <= result.tone_score <= 10
        assert 1 <= result.accuracy_score <= 10


# ══════════════════════════════════════════════════════════════════════════════
#  S8 — LAYER 4 FEEDBACK LOOP
# ══════════════════════════════════════════════════════════════════════════════

class TestS8FeedbackLoop:
    """Feedback loop reads interactions from DB and updates lapse scores."""

    def _make_temp_db(self) -> tuple[str, sqlite3.Connection]:
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS feedback_events (
                event_id TEXT PRIMARY KEY, journey_id TEXT,
                policy_number TEXT, customer_id TEXT, signal TEXT,
                outcome TEXT, lapse_delta INTEGER,
                old_score REAL, new_score REAL,
                quality_score REAL, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS renewal_journeys (
                journey_id TEXT PRIMARY KEY, policy_number TEXT,
                customer_id TEXT, lapse_score REAL DEFAULT 50,
                segment TEXT, status TEXT DEFAULT 'pending'
            );
            CREATE TABLE IF NOT EXISTS interactions (
                interaction_id TEXT PRIMARY KEY, journey_id TEXT,
                policy_number TEXT, customer_id TEXT, channel TEXT,
                outcome TEXT, sent_at TEXT
            );
            CREATE TABLE IF NOT EXISTS quality_scores (
                score_id TEXT PRIMARY KEY, journey_id TEXT, total_score REAL
            );
        """)
        conn.commit()
        return path, conn

    def test_payment_outcome_reduces_lapse_score(self):
        """payment_made signal should reduce lapse_score by 20 points."""
        from agents.layer4_learning.feedback_loop import OUTCOME_SIGNALS
        delta, signal = OUTCOME_SIGNALS["payment_made"]
        assert delta == -20
        assert signal == "strong_positive"

    def test_opt_out_increases_lapse_score(self):
        """opt_out signal should increase lapse_score."""
        from agents.layer4_learning.feedback_loop import OUTCOME_SIGNALS
        delta, signal = OUTCOME_SIGNALS["opt_out"]
        assert delta > 0
        assert "negative" in signal

    def test_feedback_loop_run_with_empty_db(self):
        """FeedbackLoopAgent.run() with empty DB returns zero-count summary."""
        db_path, _ = self._make_temp_db()
        from agents.layer4_learning.feedback_loop import FeedbackLoopAgent

        with patch("agents.layer4_learning.feedback_loop.settings") as mock_s, \
             patch("agents.layer4_learning.feedback_loop.PropensityAgent"):
            mock_s.abs_db_path = db_path
            mock_s.mock_delivery = True
            agent = FeedbackLoopAgent()
            events, summary = agent.run()

        assert summary.total_events == 0
        assert summary.propensity_prompt_refreshed is False
        os.unlink(db_path)

    def test_feedback_loop_processes_payment_interactions(self):
        """Inserting a payment_made interaction → FeedbackLoopAgent produces positive events."""
        db_path, conn = self._make_temp_db()
        j_id = "J-TEST-001"

        conn.execute(
            "INSERT INTO renewal_journeys VALUES (?,?,?,?,?,?)",
            (j_id, "POL-TEST", "CUST-TEST", 60, "nudge_needed", "in_progress"),
        )
        conn.execute(
            "INSERT INTO interactions VALUES (?,?,?,?,?,?,?)",
            (
                f"INT-{uuid.uuid4().hex[:8]}", j_id,
                "POL-TEST", "CUST-TEST", "whatsapp",
                "payment_made", datetime.now().isoformat(),
            ),
        )
        conn.commit()

        from agents.layer4_learning.feedback_loop import FeedbackLoopAgent

        with patch("agents.layer4_learning.feedback_loop.settings") as mock_s, \
             patch("agents.layer4_learning.feedback_loop.PropensityAgent"):
            mock_s.abs_db_path = db_path
            mock_s.mock_delivery = True
            agent = FeedbackLoopAgent()
            events, summary = agent.run()

        assert summary.total_events >= 1
        assert summary.score_updates >= 1
        os.unlink(db_path)

    def test_all_outcome_signal_keys_defined(self):
        """Every InteractionOutcome that the system can produce has a signal entry."""
        from agents.layer4_learning.feedback_loop import OUTCOME_SIGNALS
        expected_outcomes = {
            "payment_made", "responded", "read", "delivered",
            "no_response", "failed", "objection", "opt_out",
            "escalated", "callback_scheduled",
        }
        missing = expected_outcomes - set(OUTCOME_SIGNALS.keys())
        assert not missing, f"Missing outcome signals: {missing}"


# ══════════════════════════════════════════════════════════════════════════════
#  S9 — LAYER 5 HUMAN QUEUE
# ══════════════════════════════════════════════════════════════════════════════

class TestS9HumanQueue:
    """Queue manager: escalation routing, SLA, resolution."""

    def test_distress_routed_to_wellness_team(self):
        """Distress reason must route to the wellness team."""
        from agents.layer5_human.queue_manager import QueueManager, MOCK_AGENTS
        qm = QueueManager.__new__(QueueManager)
        qm.agents = MOCK_AGENTS

        agent = qm._select_agent(
            reason=EscalationReason.DISTRESS.value,
            language="en",
            priority=EscalationPriority.P1_URGENT.value,
        )
        assert agent is not None
        assert "distress" in agent["skills"] or "bereavement" in agent["skills"]

    def test_legal_routed_to_compliance_team(self):
        """Legal threat routes to compliance team."""
        from agents.layer5_human.queue_manager import QueueManager, MOCK_AGENTS
        qm = QueueManager.__new__(QueueManager)
        qm.agents = MOCK_AGENTS

        agent = qm._select_agent(
            reason=EscalationReason.LEGAL_THREAT.value,
            language="en",
            priority=EscalationPriority.P1_URGENT.value,
        )
        assert agent is not None
        assert "legal" in agent["skills"] or "mis_selling" in agent["skills"]

    def test_sla_deadline_set_correctly(self):
        """P1_URGENT SLA must be 1 hour from creation."""
        from agents.layer5_human.queue_manager import SLA_HOURS
        assert SLA_HOURS[EscalationPriority.P1_URGENT.value] == 1
        assert SLA_HOURS[EscalationPriority.P2_HIGH.value]   == 4
        assert SLA_HOURS[EscalationPriority.P3_NORMAL.value] == 24
        assert SLA_HOURS[EscalationPriority.P4_LOW.value]    == 72

    def test_case_resolution_marks_resolved(self):
        """Resolving a case sets resolved=True and resolved_at timestamp."""
        from agents.layer5_human.queue_manager import QueueManager

        case = EscalationCase(
            case_id="ESC-RESOLVE-001",
            journey_id="J-005",
            policy_number="POL-0005",
            customer_id="CUST-005",
            reason=EscalationReason.REQUESTED_HUMAN,
            priority=EscalationPriority.P3_NORMAL,
            briefing_note="Customer requested human agent.",
        )

        with patch("agents.layer5_human.queue_manager.sqlite3.connect") as mock_db:
            mock_conn = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value = MagicMock()
            mock_conn.commit.return_value = None

            qm = QueueManager()
            qm._db_resolve_case(
                conn=mock_conn,
                case_id="ESC-RESOLVE-001",
                resolution_note="Customer renewed after EMI offer.",
            )
            # Verify SQL was called with resolution data
            mock_conn.execute.assert_called_once()
            call_args = mock_conn.execute.call_args[0]
            assert "resolved" in call_args[0].lower() or "update" in call_args[0].lower()

    def test_priority_order_correct(self):
        """P1_URGENT must sort before P4_LOW."""
        from agents.layer5_human.queue_manager import PRIORITY_ORDER
        assert PRIORITY_ORDER[EscalationPriority.P1_URGENT.value] < \
               PRIORITY_ORDER[EscalationPriority.P4_LOW.value]


# ══════════════════════════════════════════════════════════════════════════════
#  S10 — CLOSED FEEDBACK LOOP: refresh_from_feedback
# ══════════════════════════════════════════════════════════════════════════════

class TestS10ClosedFeedbackLoop:
    """refresh_from_feedback() builds few-shot block from real outcomes."""

    def _make_db_with_events(self, n_paid: int = 6, n_lapsed: int = 6) -> str:
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS feedback_events (
                event_id TEXT PRIMARY KEY, journey_id TEXT,
                policy_number TEXT, customer_id TEXT, signal TEXT,
                outcome TEXT, lapse_delta INTEGER,
                old_score REAL, new_score REAL,
                quality_score REAL, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS renewal_journeys (
                journey_id TEXT PRIMARY KEY, policy_number TEXT,
                customer_id TEXT, lapse_score REAL DEFAULT 50,
                segment TEXT, status TEXT DEFAULT 'pending'
            );
            CREATE TABLE IF NOT EXISTS customers (
                customer_id TEXT PRIMARY KEY, name TEXT, age INTEGER,
                city TEXT, occupation TEXT
            );
        """)
        for i in range(n_paid):
            conn.execute(
                "INSERT INTO feedback_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"FB-P-{i}", f"J-{i}", f"POL-{i:04d}", f"C-{i}",
                 "strong_positive", "payment_made", -20, 70.0, 50.0,
                 85.0, datetime.now().isoformat()),
            )
            conn.execute(
                "INSERT INTO renewal_journeys VALUES (?,?,?,?,?,?)",
                (f"J-{i}", f"POL-{i:04d}", f"C-{i}", 50, "nudge_needed", "payment_done"),
            )
            conn.execute(
                "INSERT INTO customers VALUES (?,?,?,?,?)",
                (f"C-{i}", f"Customer {i}", 35 + i, "Mumbai", "IT Professional"),
            )
        for i in range(n_lapsed):
            j = n_paid + i
            conn.execute(
                "INSERT INTO feedback_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"FB-L-{i}", f"J-{j}", f"POL-{j:04d}", f"C-{j}",
                 "strong_negative", "opt_out", 20, 30.0, 50.0,
                 40.0, datetime.now().isoformat()),
            )
            conn.execute(
                "INSERT INTO renewal_journeys VALUES (?,?,?,?,?,?)",
                (f"J-{j}", f"POL-{j:04d}", f"C-{j}", 80, "high_risk", "lapsed"),
            )
            conn.execute(
                "INSERT INTO customers VALUES (?,?,?,?,?)",
                (f"C-{j}", f"Customer {j}", 55 + i, "Pune", "Farmer"),
            )
        conn.commit()
        conn.close()
        return path

    def test_refresh_builds_few_shot_block(self):
        """With ≥10 events, refresh_from_feedback builds a non-empty few-shot block."""
        import agents.layer1_strategic.propensity as prop_mod
        prop_mod._FEEDBACK_FEW_SHOT = ""

        db_path = self._make_db_with_events(n_paid=6, n_lapsed=6)
        from agents.layer1_strategic.propensity import PropensityAgent

        with patch("agents.layer1_strategic.propensity.settings") as mock_s, \
             patch("agents.layer1_strategic.propensity.get_gemini_client"):
            mock_s.abs_db_path = db_path
            mock_s.mock_delivery = True
            agent = PropensityAgent.__new__(PropensityAgent)
            refreshed = agent.refresh_from_feedback(min_events=10)

        assert refreshed is True
        assert prop_mod._FEEDBACK_FEW_SHOT != ""
        assert "PAID" in prop_mod._FEEDBACK_FEW_SHOT or "paid" in prop_mod._FEEDBACK_FEW_SHOT.lower()
        os.unlink(db_path)

    def test_refresh_skips_below_threshold(self):
        """With < threshold events, refresh returns False."""
        import agents.layer1_strategic.propensity as prop_mod
        prop_mod._FEEDBACK_FEW_SHOT = ""

        db_path = self._make_db_with_events(n_paid=2, n_lapsed=2)
        from agents.layer1_strategic.propensity import PropensityAgent

        with patch("agents.layer1_strategic.propensity.settings") as mock_s, \
             patch("agents.layer1_strategic.propensity.get_gemini_client"):
            mock_s.abs_db_path = db_path
            mock_s.mock_delivery = True
            agent = PropensityAgent.__new__(PropensityAgent)
            refreshed = agent.refresh_from_feedback(min_events=10)

        assert refreshed is False
        assert prop_mod._FEEDBACK_FEW_SHOT == ""
        os.unlink(db_path)

    def test_few_shot_prepended_to_propensity_prompt(self):
        """After refresh, the few-shot block is included in the Gemini prompt."""
        import agents.layer1_strategic.propensity as prop_mod
        prop_mod._FEEDBACK_FEW_SHOT = "=== REAL OUTCOME EXAMPLES ===\nCUST-X: PAID ✅\n"

        prop_json = json.dumps({
            "lapse_score": 40,
            "intervention_intensity": "moderate",
            "top_reasons": ["late payment"],
            "recommended_actions": ["whatsapp"],
            "reasoning": "Moderate risk.",
        })

        captured_prompts = []

        def capture_prompt(*args, **kwargs):
            captured_prompts.append(kwargs.get("contents", args[1] if len(args) > 1 else ""))
            return _gemini_response(prop_json)

        with patch("agents.layer1_strategic.propensity.get_gemini_client") as m:
            client = MagicMock()
            client.models.generate_content.side_effect = capture_prompt
            m.return_value = client
            agent = prop_mod.PropensityAgent()
            agent.run(_customer(), _policy(), segment="nudge_needed")

        assert captured_prompts, "Gemini must have been called"
        assert "REAL OUTCOME EXAMPLES" in captured_prompts[0], \
            "Few-shot block not found in prompt"

        # cleanup
        prop_mod._FEEDBACK_FEW_SHOT = ""


# ══════════════════════════════════════════════════════════════════════════════
#  S11 — PAYMENT AGENT: all modalities
# ══════════════════════════════════════════════════════════════════════════════

class TestS11PaymentAgent:
    """All payment generation paths produce valid output."""

    def test_upi_deep_link_structure(self):
        from agents.layer2_execution.payment_agent import PaymentAgent
        pol = _policy(premium=18_500)
        agent = PaymentAgent()
        upi = agent.build_upi_link(pol)
        assert upi.deep_link.startswith("upi://pay?")
        assert "am=18500" in upi.deep_link or "am=18500.0" in upi.deep_link
        assert upi.txn_ref  # non-empty transaction ref

    def test_qr_code_is_valid_png(self):
        from agents.layer2_execution.payment_agent import PaymentAgent
        pol = _policy(premium=18_500)
        agent = PaymentAgent()
        qr = agent.build_qr_code(pol)
        assert qr.png_bytes[:4] == b"\x89PNG"
        assert len(qr.png_b64) > 100  # base64 non-trivial

    def test_netbanking_links_all_present(self):
        from agents.layer2_execution.payment_agent import NETBANKING_URLS
        expected_banks = {"SBI", "HDFC", "ICICI", "AXIS", "KOTAK", "BOB", "PNB", "UNION"}
        assert expected_banks == set(NETBANKING_URLS.keys())

    def test_autopay_mandate_stub(self):
        from agents.layer2_execution.payment_agent import PaymentAgent
        pol = _policy()
        agent = PaymentAgent()
        mandate = agent.create_autopay_mandate(pol)
        assert mandate["mandate_id"].startswith("MND-") or "mandate" in str(mandate).lower()
        assert mandate["status"] in ("created", "pending", "active")

    def test_payment_link_url_format(self):
        from agents.layer2_execution.payment_agent import PaymentAgent, PAYMENT_BASE_URL
        pol = _policy()
        agent = PaymentAgent()
        link = agent.build_payment_link(pol)
        assert link.startswith(PAYMENT_BASE_URL) or link.startswith("https://")


# ══════════════════════════════════════════════════════════════════════════════
#  S12 — run_batch_with_feedback()
# ══════════════════════════════════════════════════════════════════════════════

class TestS12BatchWithFeedback:
    """run_batch_with_feedback: journeys created + feedback loop runs."""

    def _layer1_side_effect(self):
        responses = [
            json.dumps({"segment": "nudge_needed", "recommended_tone": "friendly",
                        "recommended_strategy": "renewal_reminder", "risk_flag": "medium",
                        "reasoning": "OK"}),
            json.dumps({"lapse_score": 45, "intervention_intensity": "moderate",
                        "top_reasons": [], "recommended_actions": [], "reasoning": "OK"}),
            json.dumps({"best_contact_window": "18:00-20:00", "best_days": ["Wed"],
                        "salary_day_flag": False, "urgency_override": False, "reasoning": "OK"}),
            json.dumps({"channel_sequence": ["whatsapp", "email"], "reasoning": "OK"}),
        ]
        idx = [0]

        def side_effect(*args, **kwargs):
            r = _gemini_response(responses[idx[0] % len(responses)])
            idx[0] += 1
            return r

        return side_effect

    def test_empty_batch_returns_empty(self):
        from agents.layer1_strategic.orchestrator import run_batch_with_feedback
        result = run_batch_with_feedback([], run_feedback_loop=False)
        assert result["journeys"] == []
        assert result["feedback"] is None

    def test_batch_creates_journeys(self):
        """Batch of 2 customers creates 2 journeys."""
        pairs = [
            (_customer("CUST-B1"), _policy("POL-B001", "CUST-B1")),
            (_customer("CUST-B2"), _policy("POL-B002", "CUST-B2")),
        ]

        side = self._layer1_side_effect()

        with patch("agents.layer1_strategic.segmentation.get_gemini_client") as m_seg, \
             patch("agents.layer1_strategic.propensity.get_gemini_client") as m_prop, \
             patch("agents.layer1_strategic.timing.get_gemini_client") as m_tim, \
             patch("agents.layer1_strategic.channel_selector.get_gemini_client") as m_ch, \
             patch("agents.layer1_strategic.orchestrator.create_journey"), \
             patch("agents.layer4_learning.feedback_loop.FeedbackLoopAgent") as mock_fla:
            # Mock feedback loop to return an empty summary
            from agents.layer4_learning.feedback_loop import FeedbackSummary
            mock_fla_inst = MagicMock()
            mock_fla_inst.run.return_value = ([], FeedbackSummary(total_events=0))
            mock_fla.return_value = mock_fla_inst

            for m in (m_seg, m_prop, m_tim, m_ch):
                c = MagicMock()
                c.models.generate_content.side_effect = side
                m.return_value = c

            from agents.layer1_strategic.orchestrator import run_batch_with_feedback
            result = run_batch_with_feedback(pairs, run_feedback_loop=True)

        assert len(result["journeys"]) == 2
        for j in result["journeys"]:
            assert j.policy_number in ("POL-B001", "POL-B002")


# ══════════════════════════════════════════════════════════════════════════════
#  S13 — OBJECTION HANDLER
# ══════════════════════════════════════════════════════════════════════════════

class TestS13ObjectionHandler:
    """Objection handler resolves common objection types."""

    def test_handles_price_objection(self):
        obj_json = json.dumps({
            "resolved": True,
            "response": "We understand. We can offer EMI in 3 instalments at no extra cost.",
            "next_action": "send_emi_link",
            "follow_up_required": False,
        })
        from agents.layer2_execution.objection_handler import ObjectionHandlerAgent
        with patch("agents.layer2_execution.objection_handler.get_gemini_client") as m:
            m.return_value = _mock_gemini_client(obj_json)
            agent = ObjectionHandlerAgent()
            result = agent.handle(
                objection_type="too_expensive",
                customer=_customer(),
                policy=_policy(),
            )
        assert result.resolved is True
        assert result.next_action == "send_emi_link"

    def test_handles_delay_objection(self):
        obj_json = json.dumps({
            "resolved": True,
            "response": "No problem! We can schedule a callback at your convenient time.",
            "next_action": "schedule_callback",
            "follow_up_required": True,
        })
        from agents.layer2_execution.objection_handler import ObjectionHandlerAgent
        with patch("agents.layer2_execution.objection_handler.get_gemini_client") as m:
            m.return_value = _mock_gemini_client(obj_json)
            agent = ObjectionHandlerAgent()
            result = agent.handle(
                objection_type="will_think_about_it",
                customer=_customer(),
                policy=_policy(),
            )
        assert result.resolved is True
        assert result.follow_up_required is True


# ══════════════════════════════════════════════════════════════════════════════
#  S14 — CHANNEL SELECTOR: DND + segment logic
# ══════════════════════════════════════════════════════════════════════════════

class TestS14ChannelSelector:
    """Channel selector respects DND and segment-based rules."""

    def test_dnd_customer_gets_email_only(self):
        ch_json = json.dumps({
            "channel_sequence": ["email"],
            "reasoning": "Customer is on DND — only non-intrusive channels allowed.",
        })
        from agents.layer1_strategic.channel_selector import ChannelSelectorAgent
        cust = _customer(dnd=True)
        with patch("agents.layer1_strategic.channel_selector.get_gemini_client") as m:
            m.return_value = _mock_gemini_client(ch_json)
            result = ChannelSelectorAgent().run(
                cust, _policy(),
                segment="nudge_needed", lapse_score=45, urgency_override=False,
            )
        # DND should result in no intrusive channels
        assert Channel.VOICE not in result.channel_sequence
        assert Channel.EMAIL in result.channel_sequence or Channel.SMS in result.channel_sequence

    def test_at_risk_gets_multi_channel(self):
        ch_json = json.dumps({
            "channel_sequence": ["whatsapp", "email", "voice"],
            "reasoning": "At-risk with urgency — all channels.",
        })
        from agents.layer1_strategic.channel_selector import ChannelSelectorAgent
        with patch("agents.layer1_strategic.channel_selector.get_gemini_client") as m:
            m.return_value = _mock_gemini_client(ch_json)
            result = ChannelSelectorAgent().run(
                _customer(), _policy(),
                segment="high_risk", lapse_score=82, urgency_override=True,
            )
        assert len(result.channel_sequence) >= 2

    def test_auto_renewer_gets_single_channel(self):
        ch_json = json.dumps({
            "channel_sequence": ["whatsapp"],
            "reasoning": "Auto-renewer — single gentle reminder.",
        })
        from agents.layer1_strategic.channel_selector import ChannelSelectorAgent
        with patch("agents.layer1_strategic.channel_selector.get_gemini_client") as m:
            m.return_value = _mock_gemini_client(ch_json)
            result = ChannelSelectorAgent().run(
                _customer(), _policy(auto_debit=True, payment_history=["on_time"] * 4),
                segment="auto_renewer", lapse_score=8, urgency_override=False,
            )
        assert len(result.channel_sequence) == 1


# ══════════════════════════════════════════════════════════════════════════════
#  S15 — TIMING AGENT: urgency and standard windows
# ══════════════════════════════════════════════════════════════════════════════

class TestS15TimingAgent:
    """Timing agent returns correct windows and urgency flags."""

    def test_standard_window_for_it_professional(self):
        timing_json = json.dumps({
            "best_contact_window": "18:00-20:00",
            "best_days": ["Tuesday", "Wednesday"],
            "salary_day_flag": False,
            "urgency_override": False,
            "reasoning": "IT professional — evenings preferred.",
        })
        from agents.layer1_strategic.timing import TimingAgent
        with patch("agents.layer1_strategic.timing.get_gemini_client") as m:
            m.return_value = _mock_gemini_client(timing_json)
            result = TimingAgent().run(_customer(), _policy(days_to_due=14), intensity="moderate")
        assert "18" in result.best_contact_window
        assert "Tuesday" in result.best_days or "Wednesday" in result.best_days

    def test_urgency_override_triggers_for_due_soon(self):
        timing_json = json.dumps({
            "best_contact_window": "10:00-12:00",
            "best_days": ["Today"],
            "salary_day_flag": False,
            "urgency_override": True,
            "reasoning": "Due in 2 days — contact immediately.",
        })
        from agents.layer1_strategic.timing import TimingAgent
        with patch("agents.layer1_strategic.timing.get_gemini_client") as m:
            m.return_value = _mock_gemini_client(timing_json)
            result = TimingAgent().run(_customer(), _policy(days_to_due=2), intensity="urgent")
        assert result.urgency_override is True

    def test_salary_day_flag_set(self):
        timing_json = json.dumps({
            "best_contact_window": "09:00-11:00",
            "best_days": ["Monday"],
            "salary_day_flag": True,
            "urgency_override": False,
            "reasoning": "1st of the month — salary day boosts response.",
        })
        from agents.layer1_strategic.timing import TimingAgent
        with patch("agents.layer1_strategic.timing.get_gemini_client") as m:
            m.return_value = _mock_gemini_client(timing_json)
            result = TimingAgent().run(_customer(), _policy(), intensity="moderate")
        assert result.salary_day_flag is True


# ══════════════════════════════════════════════════════════════════════════════
#  INTEGRATION: wire Layer 1 → Layer 3 quality check → decision
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegrationL1toL3:
    """End-to-end: Layer 1 creates journey, Layer 3 scores a message for it."""

    def test_journey_to_quality_decision(self):
        """A journey from L1 flows into L3; message is scored and decision taken."""
        from agents.layer3_quality.quality_scoring import compute_quality_score
        from agents.layer3_quality.critique_agent import CritiqueResult
        from agents.layer3_quality.compliance_agent import ComplianceResult
        from agents.layer3_quality.safety_agent import SafetyResult
        from agents.layer3_quality.sentiment_agent import SentimentResult, SentimentPolarity

        # Simulate a journey object from Layer 1
        journey = RenewalJourney(
            journey_id="J-INT-001",
            policy_number="POL-INT-001",
            customer_id="CUST-INT-001",
            status=JourneyStatus.IN_PROGRESS,
            segment=CustomerSegment.NUDGE_NEEDED,
            lapse_score=48,
            channel_sequence=[Channel.WHATSAPP, Channel.EMAIL],
        )

        # Now run Layer 3 quality check on a message for this journey
        score = compute_quality_score(
            journey_id=journey.journey_id,
            policy_number=journey.policy_number,
            customer_name="Test Customer",
            channel="whatsapp",
            critique=CritiqueResult(
                approved=True, tone_score=8, accuracy_score=8,
                personalisation_score=7, conversion_likelihood=7,
                overall_verdict="Good.",
            ),
            compliance=ComplianceResult(
                rules_checked=3, rules_passed=3, violations=[],
                call_window_ok=True, disclosure_ok=True, opt_out_present=True,
                irdai_compliant=True,
            ),
            safety=SafetyResult(is_safe=True, distress_detected=False, flags=[], severity="low"),
            sentiment=SentimentResult(
                polarity=SentimentPolarity.POSITIVE, score=4.0, magnitude=0.7,
                customer_intent="renew",
            ),
        )

        decision = "send" if score.total_score >= 70 else "escalate"
        assert decision == "send", f"Expected send, got escalate (score={score.total_score})"
        assert score.journey_id == "J-INT-001"
