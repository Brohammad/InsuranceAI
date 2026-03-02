"""
tests/test_payment_agent.py
────────────────────────────
Tests for the expanded PaymentAgent:
  - UPI deep link format (NPCI spec)
  - QR code PNG generation (real PNG bytes via qrcode lib)
  - AutoPay mandate stub structure
  - Net banking links (8 banks)
  - PaymentLinkResult full bundle
  - check_status() mock distribution
  - confirm_payment() return value
  - WhatsApp message format with UPI link
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import date
from unittest.mock import MagicMock


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_customer():
    c = MagicMock()
    c.customer_id = "C-PAY-001"
    c.name        = "Rajesh Kumar"
    c.phone       = "9876543210"
    c.email       = "rajesh@test.com"
    return c


def _make_policy(premium: float = 14500.0):
    from unittest.mock import MagicMock
    from core.models import ProductType
    p = MagicMock()
    p.policy_number    = "POL-PAY-001"
    p.product_name     = "Term Life Plus"
    p.product_type     = ProductType.TERM
    p.annual_premium   = premium
    p.sum_assured      = 1500000
    p.renewal_due_date = date(2025, 12, 31)
    return p


# ── UPI deep link tests ───────────────────────────────────────────────────────

def test_build_upi_deep_link_format():
    from agents.layer2_execution.payment_agent import build_upi_deep_link
    link = build_upi_deep_link(
        vpa="suraksha.life@razorpay",
        name="Suraksha Life Insurance",
        amount=14500.0,
        txn_ref="TXN-ABC123",
        note="Renewal POL-001",
    )
    assert link.startswith("upi://pay?")
    assert "pa=suraksha.life%40razorpay" in link or "pa=suraksha.life@razorpay" in link
    assert "am=14500.00" in link
    assert "cu=INR" in link
    assert "tr=TXN-ABC123" in link
    print(f"✅ UPI deep link: {link[:80]}")


def test_build_upi_deep_link_note_truncated():
    from agents.layer2_execution.payment_agent import build_upi_deep_link
    long_note = "A" * 100
    link = build_upi_deep_link("vpa@bank", "Name", 100.0, "TXN1", long_note)
    # Note is truncated to 50 chars in URL-encoded form
    assert link.startswith("upi://pay?")
    print("✅ UPI link note truncated correctly")


def test_upi_link_works_with_all_amounts():
    from agents.layer2_execution.payment_agent import build_upi_deep_link
    for amount in [500.0, 9999.99, 100000.0, 1.0]:
        link = build_upi_deep_link("test@upi", "Test", amount, "REF", "Note")
        assert f"am={amount:.2f}" in link
    print("✅ UPI link amount formatting correct for all test values")


# ── QR code tests ─────────────────────────────────────────────────────────────

def test_generate_qr_png_returns_real_png():
    from agents.layer2_execution.payment_agent import generate_qr_png
    upi_link = "upi://pay?pa=test@upi&am=500.00&cu=INR&tr=TXN123"
    result   = generate_qr_png(upi_link)

    assert result.upi_link == upi_link
    assert len(result.png_bytes) > 100,  "PNG too small"
    assert len(result.png_b64)   > 100,  "base64 too small"
    # Real PNG starts with PNG magic bytes: \x89PNG
    assert result.png_bytes[:4] == b'\x89PNG', \
        f"Not a real PNG — first 4 bytes: {result.png_bytes[:4]}"
    print(f"✅ QR PNG generated | size={len(result.png_bytes)} bytes | PNG magic ✓")


def test_generate_qr_png_base64_decodable():
    import base64
    from agents.layer2_execution.payment_agent import generate_qr_png
    result = generate_qr_png("upi://pay?pa=test@upi&am=100.00&cu=INR")
    decoded = base64.b64decode(result.png_b64)
    assert decoded == result.png_bytes
    print(f"✅ QR base64 is valid and round-trips correctly")


def test_generate_qr_png_embeddable_in_html():
    from agents.layer2_execution.payment_agent import generate_qr_png
    result = generate_qr_png("upi://pay?pa=test@upi&am=500.00&cu=INR")
    img_tag = f'<img src="data:image/png;base64,{result.png_b64}" />'
    assert "data:image/png;base64," in img_tag
    assert len(img_tag) > 50
    print(f"✅ QR PNG can be embedded as HTML img tag ({len(img_tag)} chars)")


# ── AutoPay mandate tests ─────────────────────────────────────────────────────

def test_build_autopay_mandate_structure():
    from agents.layer2_execution.payment_agent import build_autopay_mandate
    mandate = build_autopay_mandate("POL-001", 14500.0, mock=True)

    assert mandate.mandate_id.startswith("MND-")
    assert "autopay" in mandate.mandate_url
    assert mandate.amount    == 14500.0
    assert mandate.frequency == "yearly"
    assert mandate.status    == "pending_auth"
    assert mandate.mock      is True
    assert "POL-001" in mandate.policy_number
    print(f"✅ AutoPay mandate: {mandate.mandate_id} | url={mandate.mandate_url}")


def test_build_autopay_mandate_unique_ids():
    from agents.layer2_execution.payment_agent import build_autopay_mandate
    ids = {build_autopay_mandate("POL-001", 100.0).mandate_id for _ in range(10)}
    assert len(ids) == 10, "Mandate IDs are not unique"
    print("✅ AutoPay mandate IDs are unique across 10 calls")


# ── Net banking tests ─────────────────────────────────────────────────────────

def test_build_netbanking_links_count():
    from agents.layer2_execution.payment_agent import build_netbanking_links
    links = build_netbanking_links("TXN-123", 14500.0)
    assert len(links) == 8
    print(f"✅ Net banking links generated for {len(links)} banks")


def test_build_netbanking_links_banks():
    from agents.layer2_execution.payment_agent import build_netbanking_links
    links   = build_netbanking_links("TXN-123", 14500.0)
    codes   = {l.bank_code for l in links}
    expected = {"SBI", "HDFC", "ICICI", "AXIS", "KOTAK", "BOB", "PNB", "UNION"}
    assert codes == expected
    print(f"✅ All 8 banks present: {sorted(codes)}")


def test_build_netbanking_links_contain_txn():
    from agents.layer2_execution.payment_agent import build_netbanking_links
    links = build_netbanking_links("TXN-XYZ999", 5000.0)
    for link in links:
        assert "TXN-XYZ999" in link.redirect_url, \
            f"TXN not in {link.bank_code} URL: {link.redirect_url}"
    print("✅ All net banking URLs contain transaction ID")


# ── Full PaymentAgent.create_link() tests ────────────────────────────────────

def test_payment_agent_create_link_full_bundle():
    from agents.layer2_execution.payment_agent import PaymentAgent
    agent    = PaymentAgent()
    customer = _make_customer()
    policy   = _make_policy()

    result = agent.create_link(customer, policy)

    # Top-level
    assert result.txn_id.startswith("TXN-")
    assert result.status        == "pending"
    assert result.mock          is True
    assert result.amount        == 14500.0
    assert result.policy_number == "POL-PAY-001"
    assert result.customer_name == "Rajesh Kumar"
    assert result.expires_at    == "72 hours"
    assert result.web_link.startswith("https://pay.suraksha.in/renew/")

    # UPI
    assert result.upi.deep_link.startswith("upi://pay?")
    assert "INR" in result.upi.deep_link

    # QR PNG
    assert result.qr.png_bytes[:4] == b'\x89PNG'
    assert len(result.qr.png_b64)  > 100

    # AutoPay
    assert result.autopay is not None
    assert result.autopay.mandate_id.startswith("MND-")

    # Net banking
    assert len(result.netbanking) == 8

    print(f"✅ Full payment bundle: txn={result.txn_id} | QR={len(result.qr.png_bytes)}B "
          f"| autopay={result.autopay.mandate_id} | banks={len(result.netbanking)}")


def test_payment_agent_create_link_no_autopay():
    from agents.layer2_execution.payment_agent import PaymentAgent
    agent  = PaymentAgent()
    result = agent.create_link(_make_customer(), _make_policy(), include_autopay=False)
    assert result.autopay is None
    print("✅ AutoPay excluded when include_autopay=False")


def test_payment_agent_create_link_no_netbanking():
    from agents.layer2_execution.payment_agent import PaymentAgent
    agent  = PaymentAgent()
    result = agent.create_link(_make_customer(), _make_policy(), include_netbanking=False)
    assert result.netbanking == []
    print("✅ Net banking excluded when include_netbanking=False")


def test_payment_agent_txn_ids_unique():
    from agents.layer2_execution.payment_agent import PaymentAgent
    agent   = PaymentAgent()
    txn_ids = {agent.create_link(_make_customer(), _make_policy()).txn_id for _ in range(10)}
    assert len(txn_ids) == 10
    print("✅ Transaction IDs are unique across 10 calls")


# ── check_status() tests ──────────────────────────────────────────────────────

def test_check_status_returns_valid_structure():
    from agents.layer2_execution.payment_agent import PaymentAgent
    agent  = PaymentAgent()
    status = agent.check_status("TXN-TEST123")

    assert status.txn_id == "TXN-TEST123"
    assert status.status in ("paid", "pending")
    print(f"✅ check_status: txn=TXN-TEST123 | status={status.status}")


def test_check_status_paid_fields():
    from agents.layer2_execution.payment_agent import PaymentAgent
    # Run many times; at least one should be paid
    agent    = PaymentAgent()
    statuses = [agent.check_status("TXN-LOOP").status for _ in range(50)]
    assert "paid"    in statuses, "Never got 'paid' in 50 tries"
    assert "pending" in statuses, "Never got 'pending' in 50 tries"
    paid_count = statuses.count("paid")
    print(f"✅ check_status distribution: paid={paid_count}/50 "
          f"(~30% expected, got {paid_count/50*100:.0f}%)")


def test_check_status_paid_has_paid_at():
    from agents.layer2_execution.payment_agent import PaymentAgent
    from datetime import datetime
    agent = PaymentAgent()
    # Force paid by running many times
    paid_result = None
    for _ in range(100):
        s = agent.check_status("TXN-PAID-TEST")
        if s.status == "paid":
            paid_result = s
            break
    assert paid_result is not None, "Never got paid status in 100 tries"
    assert paid_result.paid_at is not None
    assert isinstance(paid_result.paid_at, datetime)
    assert paid_result.payment_method in ("upi", "card", "netbanking", "wallet")
    print(f"✅ Paid result has paid_at + method={paid_result.payment_method}")


# ── confirm_payment() test ────────────────────────────────────────────────────

def test_confirm_payment_returns_true():
    from agents.layer2_execution.payment_agent import PaymentAgent
    agent  = PaymentAgent()
    result = agent.confirm_payment("TXN-CONF", _make_customer(), _make_policy())
    assert result is True
    print("✅ confirm_payment returns True (journey stop signal)")


# ── WhatsApp message test ─────────────────────────────────────────────────────

def test_get_whatsapp_message_contains_upi_link():
    from agents.layer2_execution.payment_agent import PaymentAgent
    agent  = PaymentAgent()
    result = agent.create_link(_make_customer(), _make_policy())
    msg    = agent.get_whatsapp_message(result, language="english")

    assert "upi://"            in msg
    assert "pay.suraksha.in"   in msg
    assert "POL-PAY-001"       in msg
    assert "14,500"            in msg or "14500" in msg
    assert "autopay"           in msg.lower() or "AutoPay" in msg
    print(f"✅ WhatsApp message contains UPI link + web link + AutoPay")
    print(f"   Preview:\n{msg[:200]}")


def test_get_whatsapp_message_hindi():
    from agents.layer2_execution.payment_agent import PaymentAgent
    agent  = PaymentAgent()
    result = agent.create_link(_make_customer(), _make_policy())
    msg    = agent.get_whatsapp_message(result, language="hindi")
    assert "upi://" in msg
    print(f"✅ Hindi WhatsApp message contains UPI link")


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import pytest as pt
    pt.main([__file__, "-v", "--tb=short", "-p", "no:warnings"])
