"""
tests/test_observability.py
────────────────────────────
Unit tests for:
  • observability/cost_tracker.py  — CostTracker
  • observability/audit_trail.py   — AuditTrail
All tests use a temp SQLite DB, no real APIs, no .env needed.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Temp DB + settings mock ───────────────────────────────────────────────────

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
TMP_DB = _TMP.name


class _MockSettings:
    abs_db_path  = TMP_DB
    mock_delivery = True
    gemini_api_key = "test"


@pytest.fixture(scope="module", autouse=True)
def mock_settings():
    with patch("observability.cost_tracker.settings", _MockSettings()), \
         patch("observability.audit_trail.settings", _MockSettings()):
        yield
    Path(TMP_DB).unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# CostTracker helpers
# ─────────────────────────────────────────────────────────────────────────────

from observability.cost_tracker import (
    CostTracker,
    calc_gemini_cost,
    calc_elevenlabs_cost,
    calc_twilio_cost,
    calc_razorpay_cost,
    USD_TO_INR,
    DAILY_BUDGET_INR,
)


# ── Pricing helpers ───────────────────────────────────────────────────────────

def test_gemini_cost_flash():
    cost = calc_gemini_cost("gemini-2.5-flash", 1000, 500)
    # input: 1000/1000 * 0.00015 = 0.00015
    # output: 500/1000 * 0.00060 = 0.00030
    assert abs(cost - 0.00045) < 1e-8

def test_gemini_cost_pro():
    cost = calc_gemini_cost("gemini-3.1-pro-preview", 1000, 500)
    # input: 0.00125, output: 0.00250
    assert abs(cost - 0.00375) < 1e-6

def test_gemini_cost_unknown_model_falls_back():
    # Unknown model → uses flash pricing
    cost_unknown = calc_gemini_cost("gemini-unknown", 1000, 1000)
    cost_flash   = calc_gemini_cost("gemini-2.5-flash", 1000, 1000)
    assert abs(cost_unknown - cost_flash) < 1e-8

def test_elevenlabs_cost():
    cost = calc_elevenlabs_cost(1000)
    assert abs(cost - 0.00030) < 1e-8

def test_twilio_cost_single():
    cost = calc_twilio_cost(1)
    assert abs(cost - 0.00500) < 1e-8

def test_twilio_cost_multiple():
    cost = calc_twilio_cost(3)
    assert abs(cost - 0.01500) < 1e-6

def test_razorpay_cost():
    cost = calc_razorpay_cost(1)
    assert abs(cost - 0.00200) < 1e-8


# ── CostTracker record methods ────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tracker():
    return CostTracker()

def test_record_gemini_returns_event(tracker):
    ev = tracker.record_gemini(
        agent_name="orchestrator",
        model="gemini-3.1-pro-preview",
        input_tokens=500,
        output_tokens=200,
        journey_id="JRN-T01",
    )
    assert ev.event_id
    assert ev.api == "gemini"
    assert ev.model == "gemini-3.1-pro-preview"
    assert ev.input_tokens == 500
    assert ev.output_tokens == 200
    assert ev.cost_usd > 0
    assert ev.cost_inr == round(ev.cost_usd * USD_TO_INR, 6)

def test_record_elevenlabs(tracker):
    ev = tracker.record_elevenlabs(
        agent_name="voice_agent",
        char_count=2000,
        journey_id="JRN-T01",
    )
    assert ev.api == "elevenlabs"
    assert ev.input_tokens == 2000
    assert ev.cost_usd > 0

def test_record_twilio(tracker):
    ev = tracker.record_twilio(
        agent_name="whatsapp_agent",
        message_count=2,
        journey_id="JRN-T01",
    )
    assert ev.api == "twilio"
    assert ev.input_tokens == 2
    expected = calc_twilio_cost(2)
    assert abs(ev.cost_usd - expected) < 1e-8

def test_record_razorpay(tracker):
    ev = tracker.record_razorpay(
        agent_name="payment_agent",
        journey_id="JRN-T01",
    )
    assert ev.api == "razorpay"
    assert ev.cost_usd > 0

def test_event_persisted_to_db(tracker):
    ev = tracker.record_gemini(
        agent_name="critique_agent",
        model="gemini-2.5-pro",
        input_tokens=300,
        output_tokens=100,
        journey_id="JRN-T02",
    )
    conn = sqlite3.connect(TMP_DB)
    row = conn.execute(
        "SELECT * FROM cost_events WHERE event_id=?", (ev.event_id,)
    ).fetchone()
    conn.close()
    assert row is not None

def test_event_cost_inr_is_usd_times_rate(tracker):
    ev = tracker.record_gemini(
        agent_name="safety_agent",
        model="gemini-2.5-flash",
        input_tokens=100,
        output_tokens=50,
    )
    assert abs(ev.cost_inr - ev.cost_usd * USD_TO_INR) < 0.0001


# ── Query methods ─────────────────────────────────────────────────────────────

def test_daily_summary_structure(tracker):
    summary = tracker.daily_summary()
    assert summary.day
    assert summary.total_calls >= 0
    assert summary.total_tokens >= 0
    assert summary.total_cost_usd >= 0
    assert isinstance(summary.over_budget, bool)

def test_daily_summary_counts_match(tracker):
    # All events seeded above should appear today
    summary = tracker.daily_summary()
    assert summary.total_calls >= 4   # at least the 4 recorded above

def test_journey_summary(tracker):
    s = tracker.journey_summary("JRN-T01")
    assert s.journey_id == "JRN-T01"
    assert s.total_calls >= 3          # gemini + elevenlabs + twilio + razorpay
    assert s.total_cost_inr >= 0
    assert isinstance(s.breakdown, dict)

def test_journey_summary_breakdown_keys(tracker):
    s = tracker.journey_summary("JRN-T01")
    assert "gemini" in s.breakdown
    assert "elevenlabs" in s.breakdown
    assert "twilio" in s.breakdown
    assert "razorpay" in s.breakdown

def test_journey_summary_unknown_journey(tracker):
    s = tracker.journey_summary("JRN-NOTEXIST")
    assert s.total_calls == 0
    assert s.total_cost_inr == 0

def test_top_agents(tracker):
    agents = tracker.top_agents()
    assert isinstance(agents, list)
    if agents:
        assert "agent" in agents[0]
        assert "calls" in agents[0]
        assert "cost_inr" in agents[0]

def test_top_agents_sorted_desc(tracker):
    agents = tracker.top_agents()
    costs = [a["cost_inr"] for a in agents]
    assert costs == sorted(costs, reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# AuditTrail tests
# ─────────────────────────────────────────────────────────────────────────────

from observability.audit_trail import (
    AuditTrail,
    AuditCategory,
    AuditOutcome,
    AuditRecord,
)


@pytest.fixture(scope="module")
def audit():
    return AuditTrail()


def test_audit_log_returns_record(audit):
    rec = audit.log(
        category    = AuditCategory.COMMUNICATION,
        action      = "whatsapp_sent",
        outcome     = AuditOutcome.SUCCESS,
        actor       = "whatsapp_agent",
        journey_id  = "JRN-A01",
        customer_id = "CUST-A01",
    )
    assert isinstance(rec, AuditRecord)
    assert rec.record_id
    assert rec.category == "communication"
    assert rec.action == "whatsapp_sent"
    assert rec.outcome == "success"

def test_audit_log_persisted(audit):
    rec = audit.log(
        category    = AuditCategory.PAYMENT,
        action      = "payment_link_created",
        outcome     = AuditOutcome.SUCCESS,
        actor       = "payment_agent",
        journey_id  = "JRN-A01",
        customer_id = "CUST-A01",
        policy_no   = "POL-A01",
        detail      = {"amount": 25000},
    )
    conn = sqlite3.connect(TMP_DB)
    row = conn.execute(
        "SELECT * FROM audit_trail WHERE record_id=?", (rec.record_id,)
    ).fetchone()
    conn.close()
    assert row is not None

def test_audit_detail_json(audit):
    detail = {"channel": "whatsapp", "language": "hi", "score": 88}
    rec = audit.log(
        category = AuditCategory.AGENT_ACTION,
        action   = "message_approved",
        detail   = detail,
        actor    = "critique_agent",
    )
    parsed = json.loads(rec.detail)
    assert parsed["channel"] == "whatsapp"
    assert parsed["score"] == 88

def test_audit_chain_hash_is_64_chars(audit):
    rec = audit.log(
        category = AuditCategory.SYSTEM,
        action   = "startup",
        actor    = "system",
    )
    assert len(rec.chain_hash) == 64

def test_audit_chain_hash_unique(audit):
    r1 = audit.log(category=AuditCategory.SYSTEM, action="event1", actor="system")
    r2 = audit.log(category=AuditCategory.SYSTEM, action="event2", actor="system")
    assert r1.chain_hash != r2.chain_hash

def test_audit_log_escalation_wrapper(audit):
    rec = audit.log_escalation(
        action      = "case_created",
        outcome     = AuditOutcome.SUCCESS,
        actor       = "orchestrator",
        journey_id  = "JRN-A01",
        customer_id = "CUST-A01",
        detail      = {"reason": "distress"},
    )
    assert rec.category == "escalation"

def test_audit_log_payment_wrapper(audit):
    rec = audit.log_payment(
        action    = "upi_qr_generated",
        outcome   = AuditOutcome.SUCCESS,
        policy_no = "POL-A01",
        detail    = {"amount": 18000},
    )
    assert rec.category == "payment"

def test_audit_log_communication_wrapper(audit):
    rec = audit.log_communication(
        channel     = "email",
        actor       = "email_agent",
        outcome     = AuditOutcome.SUCCESS,
        journey_id  = "JRN-A01",
        customer_id = "CUST-A01",
    )
    assert rec.category == "communication"
    assert rec.action == "email_sent"

def test_audit_log_blocked_outcome(audit):
    rec = audit.log(
        category = AuditCategory.COMPLIANCE,
        action   = "call_blocked_irdai_window",
        outcome  = AuditOutcome.BLOCKED,
        actor    = "voice_agent",
        detail   = {"reason": "outside 8AM-8PM IST"},
    )
    assert rec.outcome == "blocked"

def test_audit_get_journey_trail(audit):
    trail = audit.get_journey_trail("JRN-A01")
    assert len(trail) >= 3   # communication + payment + escalation logged above
    assert all(isinstance(r, AuditRecord) for r in trail)

def test_audit_journey_trail_ordered(audit):
    trail = audit.get_journey_trail("JRN-A01")
    timestamps = [r.recorded_at for r in trail]
    assert timestamps == sorted(timestamps)

def test_audit_get_customer_trail(audit):
    trail = audit.get_customer_trail("CUST-A01")
    assert len(trail) >= 2
    assert all(r.customer_id == "CUST-A01" for r in trail)

def test_audit_verify_chain_valid(audit):
    result = audit.verify_chain()
    assert result["valid"] is True
    assert result["checked"] >= 1
    assert result["errors"] == []

def test_audit_daily_count(audit):
    counts = audit.daily_count()
    assert isinstance(counts, dict)
    # We've logged communication, payment, agent_action, system, escalation, compliance
    assert len(counts) >= 3

def test_audit_daily_count_categories(audit):
    counts = audit.daily_count()
    expected_cats = {"communication","payment","escalation","system","compliance","agent_action"}
    assert expected_cats <= set(counts.keys())
