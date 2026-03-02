"""
tests/test_integrations.py
───────────────────────────
Unit tests for all 4 integration stubs:
  • integrations/crm_stub.py
  • integrations/pas_stub.py
  • integrations/irdai_stub.py
  • integrations/payment_gw_stub.py

All run in mock mode (settings.mock_delivery = True).
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Shared mock settings ───────────────────────────────────────────────────────

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
TMP_DB = _TMP.name


class _MockSettings:
    mock_delivery    = True
    abs_db_path      = TMP_DB
    gemini_api_key   = "test"
    razorpay_key_id  = "rzp_test_key"
    razorpay_key_secret = "rzp_test_secret"


@pytest.fixture(scope="module", autouse=True)
def mock_settings():
    with patch("integrations.crm_stub.settings",     _MockSettings()), \
         patch("integrations.pas_stub.settings",     _MockSettings()), \
         patch("integrations.irdai_stub.settings",   _MockSettings()), \
         patch("integrations.payment_gw_stub.settings", _MockSettings()):
        yield
    Path(TMP_DB).unlink(missing_ok=True)


# ── DB table for payment_gw_stub _mark_payment_received ──────────────────────

@pytest.fixture(scope="module", autouse=True)
def seed_db():
    conn = sqlite3.connect(TMP_DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS renewal_journeys (
            journey_id TEXT PRIMARY KEY,
            policy_number TEXT,
            customer_id TEXT,
            status TEXT DEFAULT 'in_progress',
            payment_received INTEGER DEFAULT 0,
            payment_received_at TEXT,
            segment TEXT,
            lapse_score REAL,
            channel_sequence TEXT,
            steps TEXT,
            current_step_index INTEGER,
            escalated INTEGER DEFAULT 0,
            escalation_reason TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS policies (
            policy_number TEXT PRIMARY KEY,
            customer_id TEXT,
            product_type TEXT DEFAULT '',
            product_name TEXT DEFAULT '',
            sum_assured REAL DEFAULT 0,
            annual_premium REAL DEFAULT 0,
            policy_start_date TEXT DEFAULT '',
            renewal_due_date TEXT DEFAULT '',
            tenure_years INTEGER DEFAULT 0,
            years_completed INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            payment_mode TEXT DEFAULT '',
            has_auto_debit INTEGER DEFAULT 0,
            payment_history TEXT DEFAULT '',
            last_payment_date TEXT DEFAULT '',
            grace_period_days INTEGER DEFAULT 30
        );
    """)
    conn.execute("""
        INSERT OR IGNORE INTO renewal_journeys
        (journey_id, policy_number, customer_id, status, payment_received)
        VALUES ('JRN-INT-001','POL-INT-001','CUST-INT-001','in_progress',0)
    """)
    conn.execute("""
        INSERT OR IGNORE INTO policies
        (policy_number, customer_id, status)
        VALUES ('POL-INT-001','CUST-INT-001','active')
    """)
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# CRM Stub tests
# ─────────────────────────────────────────────────────────────────────────────

from integrations.crm_stub import CrmStub, CrmContact, CrmInteractionLog, CrmTask


@pytest.fixture(scope="module")
def crm():
    return CrmStub()


def test_crm_upsert_returns_contact(crm):
    c = crm.upsert_contact("CUST-001","Ravi Kumar","9999000001","r@t.com","Mumbai","hi")
    assert isinstance(c, CrmContact)
    assert c.crm_id == "CRM-CUST-001"
    assert c.mock is True

def test_crm_upsert_name_preserved(crm):
    c = crm.upsert_contact("CUST-002","Priya Menon","9999000002","p@t.com")
    assert c.name == "Priya Menon"

def test_crm_log_interaction_returns_log(crm):
    log = crm.log_interaction("CUST-001","whatsapp","outbound","Policy renewal msg","delivered")
    assert isinstance(log, CrmInteractionLog)
    assert log.channel == "whatsapp"
    assert log.mock is True

def test_crm_log_interaction_summary_truncated(crm):
    long_msg = "A" * 300
    log = crm.log_interaction("CUST-001","email","outbound",long_msg,"opened")
    assert len(log.summary) <= 200

def test_crm_get_contact_returns_contact(crm):
    c = crm.get_contact("CUST-001")
    assert isinstance(c, CrmContact)
    assert c.customer_id == "CUST-001"

def test_crm_update_journey_status_true(crm):
    result = crm.update_journey_status("CUST-001","POL-001","renewed","Payment received")
    assert result is True

def test_crm_create_task_returns_task(crm):
    task = crm.create_follow_up_task("CUST-001","Call back customer",24,"agent_ravi","high")
    assert isinstance(task, CrmTask)
    assert "CUST-001" in task.crm_id
    assert task.priority == "high"

def test_crm_task_has_future_due_date(crm):
    from datetime import datetime
    task = crm.create_follow_up_task("CUST-001","Follow up",48)
    due = datetime.fromisoformat(task.due_date)
    assert due > datetime.now()


# ─────────────────────────────────────────────────────────────────────────────
# PAS Stub tests
# ─────────────────────────────────────────────────────────────────────────────

from integrations.pas_stub import PasStub, PasPolicy, PasRenewalUpdate, PasEndorsement


@pytest.fixture(scope="module")
def pas():
    return PasStub()


def test_pas_get_policy_returns_policy(pas):
    p = pas.get_policy("POL-001")
    assert isinstance(p, PasPolicy)
    assert p.policy_number == "POL-001"
    assert p.annual_premium > 0

def test_pas_update_renewal_status_renewed(pas):
    u = pas.update_renewal_status("POL-001", "renewed", "Payment via UPI")
    assert isinstance(u, PasRenewalUpdate)
    assert u.new_status == "renewed"
    assert u.ref_id.startswith("PAS-REF-")

def test_pas_update_renewal_status_lapsed(pas):
    u = pas.update_renewal_status("POL-002","lapsed","Grace period expired")
    assert u.new_status == "lapsed"

def test_pas_update_invalid_status_raises(pas):
    with pytest.raises(ValueError, match="Invalid PAS status"):
        pas.update_renewal_status("POL-001","invalid_xyz")

def test_pas_issue_endorsement(pas):
    e = pas.issue_endorsement("POL-001","address_change","New address: Mumbai")
    assert isinstance(e, PasEndorsement)
    assert e.endorsement_id.startswith("ENDO-")

def test_pas_apply_grace_period(pas):
    result = pas.apply_grace_period("POL-001", 30)
    assert result["approved"] is True
    assert result["extension_days"] == 30
    assert "new_deadline" in result

def test_pas_grace_period_over_limit_raises(pas):
    with pytest.raises(ValueError, match="90 days"):
        pas.apply_grace_period("POL-001", 91)

def test_pas_get_payment_history(pas):
    records = pas.get_payment_history("POL-001", 3)
    assert len(records) == 3
    assert all(r.status == "success" for r in records)

def test_pas_get_payment_history_amount(pas):
    records = pas.get_payment_history("POL-001", 1)
    assert records[0].amount == 25000.0

def test_pas_trigger_lapse(pas):
    result = pas.trigger_lapse("POL-003", "non_payment")
    assert result is True


# ─────────────────────────────────────────────────────────────────────────────
# IRDAI Stub tests
# ─────────────────────────────────────────────────────────────────────────────

from integrations.irdai_stub import (
    IrdaiStub,
    IrdaiGrievance,
    IrdaiCommunicationLog,
    PersistencyStats,
    check_call_compliance,
)


@pytest.fixture(scope="module")
def irdai():
    return IrdaiStub()


def test_irdai_report_communication(irdai):
    log = irdai.report_communication("POL-001","whatsapp","outbound","hi","delivered")
    assert isinstance(log, IrdaiCommunicationLog)
    assert log.policy_number == "POL-001"

def test_irdai_file_grievance_structure(irdai):
    g = irdai.file_grievance("POL-001","CUST-001","mis_selling","Was sold wrong product")
    assert isinstance(g, IrdaiGrievance)
    assert g.status == "filed"
    assert g.grievance_id.startswith("GRV-")

def test_irdai_grievance_ack_deadline_after_filed(irdai):
    from datetime import datetime
    g = irdai.file_grievance("POL-002","CUST-002","claim_rejection","Claim denied")
    filed = datetime.fromisoformat(g.filed_at)
    ack   = datetime.strptime(g.ack_deadline, "%Y-%m-%d")
    assert ack > filed.replace(tzinfo=None)

def test_irdai_grievance_resolve_deadline_14_days(irdai):
    from datetime import datetime, timedelta
    g = irdai.file_grievance("POL-003","CUST-003","service_failure","Delayed response")
    filed   = datetime.fromisoformat(g.filed_at).date()
    resolve = datetime.strptime(g.resolve_deadline, "%Y-%m-%d").date()
    assert (resolve - filed).days == 14

def test_irdai_acknowledge_grievance(irdai):
    g   = irdai.file_grievance("POL-001","CUST-001","other","General issue")
    ack = irdai.acknowledge_grievance(g.grievance_id)
    assert ack["acknowledged"] is True
    assert ack["grievance_id"] == g.grievance_id

def test_irdai_resolve_grievance(irdai):
    g   = irdai.file_grievance("POL-001","CUST-001","other","Resolved issue")
    res = irdai.resolve_grievance(g.grievance_id,"Customer satisfied","renewai_system")
    assert res["resolved"] is True
    assert "resolution" in res

def test_irdai_persistency_stats(irdai):
    stats = irdai.get_persistency_stats("POL-001")
    assert isinstance(stats, PersistencyStats)
    assert 0 < stats.ratio_13m <= 100
    assert stats.ratio_13m >= stats.ratio_61m  # decay expected

def test_irdai_call_compliance_structure():
    result = check_call_compliance()
    assert "allowed" in result
    assert "current_ist" in result
    assert "next_window" in result
    assert isinstance(result["allowed"], bool)

def test_irdai_static_call_window(irdai):
    result = irdai.check_call_window()
    assert "allowed" in result


# ─────────────────────────────────────────────────────────────────────────────
# Payment Gateway Stub tests
# ─────────────────────────────────────────────────────────────────────────────

from integrations.payment_gw_stub import (
    PaymentGatewayStub,
    WebhookResult,
    PaymentVerification,
    verify_razorpay_signature,
)


@pytest.fixture(scope="module")
def pgw():
    return PaymentGatewayStub()


def _make_webhook_body(event: str, policy_number: str = "POL-INT-001") -> bytes:
    payload = {
        "event": event,
        "payload": {
            "payment": {
                "entity": {
                    "id":       f"pay_{event[:4]}test001",
                    "order_id": "order_test001",
                    "amount":   2500000,
                    "status":   "captured" if event == "payment.captured" else "failed",
                    "notes":    {"policy_number": policy_number},
                }
            }
        }
    }
    return json.dumps(payload).encode()


def test_pgw_parse_webhook_captured(pgw):
    body   = _make_webhook_body("payment.captured")
    result = pgw.parse_webhook(body, "mock_sig")
    assert isinstance(result, WebhookResult)
    assert result.event   == "payment.captured"
    assert result.amount_inr == 25000.0
    assert result.mock is True

def test_pgw_parse_webhook_failed(pgw):
    body   = _make_webhook_body("payment.failed")
    result = pgw.parse_webhook(body, "mock_sig")
    assert result.event == "payment.failed"

def test_pgw_parse_webhook_extracts_policy_number(pgw):
    body   = _make_webhook_body("payment.captured","POL-TEST-99")
    result = pgw.parse_webhook(body,"mock_sig")
    assert result.policy_number == "POL-TEST-99"

def test_pgw_parse_webhook_invalid_json(pgw):
    with pytest.raises(ValueError, match="Invalid webhook JSON"):
        pgw.parse_webhook(b"not json","mock_sig")

def test_pgw_payment_captured_updates_db(pgw):
    body = _make_webhook_body("payment.captured","POL-INT-001")
    pgw.parse_webhook(body,"mock_sig")
    conn = sqlite3.connect(TMP_DB)
    row  = conn.execute(
        "SELECT payment_received, status FROM renewal_journeys WHERE policy_number=?",
        ("POL-INT-001",)
    ).fetchone()
    conn.close()
    assert row[0] == 1
    assert row[1] == "renewed"

def test_pgw_verify_payment_mock(pgw):
    v = pgw.verify_payment("pay_test001")
    assert isinstance(v, PaymentVerification)
    assert v.verified is True
    assert v.status == "captured"
    assert v.mock is True

def test_pgw_verify_signature_correct():
    secret  = "webhook_secret_123"
    body    = b'{"event":"payment.captured"}'
    import hmac as _hmac, hashlib as _hashlib
    sig = _hmac.new(secret.encode(), body, _hashlib.sha256).hexdigest()
    assert verify_razorpay_signature(body, sig, secret) is True

def test_pgw_verify_signature_wrong():
    assert verify_razorpay_signature(b"body","wrong_sig","secret") is False
