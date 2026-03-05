"""
agents/layer2_execution/payment_agent.py
──────────────────────────────────────────
Payment Agent — Layer 2

Handles all payment modalities for policy renewal:

  1. UPI Deep Link     — upi:// spec (NPCI standard), works with any UPI app
  2. QR Code           — PNG generated via qrcode lib, base64-encoded
  3. AutoPay / eMandate— NACH/UPI AutoPay mandate stub (Razorpay)
  4. Net Banking       — Redirect URL for 8 major Indian banks
  5. Payment Link      — Short web URL (pay.suraksha.in/renew/<txn>)

MOCK MODE (settings.mock_delivery = True):
  - Generates real UPI deep links and real QR PNG (no gateway needed)
  - 30% of check_status() calls return "paid" to exercise journey stop logic
  - AutoPay returns a mandate ID stub

REAL MODE (settings.mock_delivery = False):
  - Razorpay order API for web payment link
  - NPCI-spec UPI link with merchant VPA
  - UPI AutoPay mandate via Razorpay subscriptions API
"""

from __future__ import annotations

import base64
import io
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode, quote

from loguru import logger

from core.config import settings
from core.models import Customer, Policy
from agents.layer2_execution.mock_utils import mock_payment_link


# ── UPI constants ─────────────────────────────────────────────────────────────

MERCHANT_VPA     = "suraksha.life@razorpay"
MERCHANT_NAME    = "Suraksha Life Insurance"
PAYMENT_BASE_URL = "https://pay.suraksha.in/renew"

NETBANKING_URLS: dict[str, str] = {
    "SBI":   "https://retail.onlinesbi.com/retail/login.htm",
    "HDFC":  "https://netbanking.hdfcbank.com/netbanking/",
    "ICICI": "https://infinity.icicibank.com/corp/AuthenticationController",
    "AXIS":  "https://retail.axisbank.co.in/wps/portal/GB/retail-banking",
    "KOTAK": "https://netbanking.kotak.com/knb2/",
    "BOB":   "https://www.bobibanking.com/",
    "PNB":   "https://www.netpnb.com/",
    "UNION": "https://www.unionbankonline.co.in/",
}


# ── Output dataclasses ────────────────────────────────────────────────────────

@dataclass
class UpiDetails:
    vpa:        str
    amount:     float
    txn_ref:    str
    txn_note:   str
    deep_link:  str
    intent_url: str


@dataclass
class QrResult:
    png_bytes: bytes
    png_b64:   str
    upi_link:  str
    size_px:   int = 300


@dataclass
class AutoPayMandate:
    mandate_id:    str
    mandate_url:   str
    amount:        float
    frequency:     str
    policy_number: str
    status:        str
    mock:          bool = True


@dataclass
class NetBankingLink:
    bank_code:    str
    bank_name:    str
    redirect_url: str
    txn_id:       str


@dataclass
class PaymentLinkResult:
    txn_id:        str
    upi:           UpiDetails
    qr:            QrResult
    web_link:      str
    autopay:       Optional[AutoPayMandate]
    netbanking:    list
    amount:        float
    policy_number: str
    customer_name: str
    status:        str
    created_at:    datetime
    expires_at:    str
    mock:          bool = True


@dataclass
class PaymentStatusResult(str):
    """
    String subclass so `result in ("paid","pending","failed")` works,
    while also carrying structured fields (.txn_id, .status, .paid_at, etc.)
    """
    txn_id:         str
    status:         str
    paid_at:        Optional[datetime]
    amount_paid:    Optional[float]
    payment_method: Optional[str]
    mandate_id:     Optional[str]

    def __new__(cls, status: str, txn_id: str = "",
                paid_at: Optional[datetime] = None,
                amount_paid: Optional[float] = None,
                payment_method: Optional[str] = None,
                mandate_id: Optional[str] = None):
        instance = super().__new__(cls, status)
        instance.status         = status
        instance.txn_id         = txn_id
        instance.paid_at        = paid_at
        instance.amount_paid    = amount_paid
        instance.payment_method = payment_method
        instance.mandate_id     = mandate_id
        return instance

    def __init__(self, status: str, txn_id: str = "",
                 paid_at: Optional[datetime] = None,
                 amount_paid: Optional[float] = None,
                 payment_method: Optional[str] = None,
                 mandate_id: Optional[str] = None):
        # All initialization happens in __new__; str.__init__ doesn't accept args
        # Call super().__init__ without extra args to avoid TypeError.
        super().__init__()


# ── UPI deep link builder ─────────────────────────────────────────────────────

def build_upi_deep_link(vpa: str, name: str, amount: float,
                        txn_ref: str, note: str) -> str:
    """
    Build NPCI-compliant UPI deep link.
    upi://pay?pa=<vpa>&pn=<name>&am=<amount>&tn=<note>&tr=<ref>&cu=INR
    Works with PhonePe, GPay, Paytm, BHIM, Amazon Pay, etc.
    """
    params = {
        "pa": vpa,
        "pn": name,
        "am": f"{amount:.2f}",
        "tn": note[:50],
        "tr": txn_ref,
        "cu": "INR",
    }
    return "upi://pay?" + urlencode(params, quote_via=lambda s, safe, encoding=None, errors=None: quote(s, safe="@"))


# ── QR code generator ─────────────────────────────────────────────────────────

def generate_qr_png(upi_link: str, size: int = 300) -> QrResult:
    """Generate a QR code PNG from a UPI deep link. Returns bytes + base64."""
    try:
        import qrcode
        from qrcode.constants import ERROR_CORRECT_L

        qr = qrcode.QRCode(
            version=1, error_correction=ERROR_CORRECT_L,
            box_size=10, border=4,
        )
        qr.add_data(upi_link)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        return QrResult(
            png_bytes=png_bytes,
            png_b64=base64.b64encode(png_bytes).decode(),
            upi_link=upi_link,
            size_px=size,
        )
    except ImportError:
        logger.warning("qrcode library not found — returning stub QR")
        stub = f"[QR_STUB:{upi_link[:40]}]".encode()
        return QrResult(
            png_bytes=stub,
            png_b64=base64.b64encode(stub).decode(),
            upi_link=upi_link,
            size_px=size,
        )


# ── AutoPay mandate builder ───────────────────────────────────────────────────

def build_autopay_mandate(policy_number: str, amount: float,
                          mock: bool = True) -> AutoPayMandate:
    """Build a UPI AutoPay / NACH eMandate stub."""
    mandate_id = f"MND-{uuid.uuid4().hex[:10].upper()}"
    return AutoPayMandate(
        mandate_id=mandate_id,
        mandate_url=f"https://pay.suraksha.in/autopay/{mandate_id}",
        amount=amount,
        frequency="yearly",
        policy_number=policy_number,
        status="pending_auth",
        mock=mock,
    )


# ── Net banking links ─────────────────────────────────────────────────────────

def build_netbanking_links(txn_id: str, amount: float) -> list:
    """Build redirect links for top 8 Indian banks."""
    links = []
    for code, base_url in NETBANKING_URLS.items():
        redirect = (
            f"{base_url}?merchant=SURAKSHA_LIFE"
            f"&txn={txn_id}&amount={amount:.0f}&currency=INR"
        )
        links.append(NetBankingLink(
            bank_code=code, bank_name=code,
            redirect_url=redirect, txn_id=txn_id,
        ))
    return links


# ── Agent ─────────────────────────────────────────────────────────────────────

class PaymentAgent:
    """
    Generates and tracks all payment modalities:
    UPI deep link, QR PNG, AutoPay mandate, net banking, web link.
    """

    MOCK_PAID_RATE = 0.30

    def __init__(self, mock: bool | None = None):
        # Allow explicit override for tests. If not provided, prefer settings.mock_delivery,
        # but default to mock mode when Razorpay credentials are missing (safe fallback).
        if mock is not None:
            self.mock = mock
        else:
            if not settings.razorpay_key_id or not settings.razorpay_key_secret:
                # No real gateway configured — run in mock mode by default
                self.mock = True
            else:
                self.mock = settings.mock_delivery
        logger.info(f"PaymentAgent ready | mock={self.mock}")

    def create_link(
        self,
        customer:           Customer,
        policy:             Policy,
        include_autopay:    bool = True,
        include_netbanking: bool = True,
    ) -> PaymentLinkResult:
        """Create a full payment bundle (UPI + QR + AutoPay + NetBanking + Web)."""
        logger.debug(
            f"Creating payment bundle | {policy.policy_number} "
            f"| Rs.{policy.annual_premium:,.0f} | customer={customer.name}"
        )

        txn_id   = f"TXN-{uuid.uuid4().hex[:10].upper()}"
        amount   = policy.annual_premium
        note     = f"Renewal {policy.policy_number}"
        web_link = f"{PAYMENT_BASE_URL}/{txn_id}"

        # UPI deep link
        upi_link = build_upi_deep_link(
            vpa=MERCHANT_VPA, name=MERCHANT_NAME,
            amount=amount, txn_ref=txn_id, note=note,
        )
        upi = UpiDetails(
            vpa=MERCHANT_VPA, amount=amount, txn_ref=txn_id,
            txn_note=note, deep_link=upi_link, intent_url=upi_link,
        )

        # QR code (real PNG, even in mock mode — no API needed)
        qr = generate_qr_png(upi_link)
        _is_real_png = qr.png_bytes[:4] == b'\x89PNG'
        logger.debug(f"QR generated | {len(qr.png_bytes)} bytes | is_real_png={_is_real_png}")

        # AutoPay mandate
        autopay = build_autopay_mandate(policy.policy_number, amount, mock=self.mock) if include_autopay else None

        # Net banking redirects
        netbanking = build_netbanking_links(txn_id, amount) if include_netbanking else []

        # Real mode: create Razorpay order
        if not self.mock:
            rz_link = self._create_razorpay_order(customer, policy, txn_id)
            if rz_link:
                web_link = rz_link
            if include_autopay and autopay:
                autopay = self._create_real_mandate(customer, policy, txn_id, autopay)

        result = PaymentLinkResult(
            txn_id=txn_id, upi=upi, qr=qr, web_link=web_link,
            autopay=autopay, netbanking=netbanking,
            amount=amount, policy_number=policy.policy_number,
            customer_name=customer.name, status="pending",
            created_at=datetime.now(), expires_at="72 hours",
            mock=self.mock,
        )

        logger.info(
            f"Payment bundle | txn={txn_id} | Rs.{amount:,.0f} "
            f"| qr={len(qr.png_bytes)}B | autopay={'yes' if autopay else 'no'} "
            f"| banks={len(netbanking)} | mock={self.mock}"
        )
        return result

    def check_status(self, txn_id: str) -> "PaymentStatusResult":
        """Poll payment status. Returns a PaymentStatusResult (also a str: 'paid'|'pending'|'failed')."""
        if self.mock:
            paid = random.random() < self.MOCK_PAID_RATE
            if paid:
                return PaymentStatusResult(
                    "paid", txn_id=txn_id,
                    paid_at=datetime.now(),
                    amount_paid=round(random.uniform(5000, 200000), 2),
                    payment_method=random.choice(["upi", "card", "netbanking", "wallet"]),
                )
            return PaymentStatusResult("pending", txn_id=txn_id)
        try:
            import razorpay
            client = razorpay.Client(auth=(
                settings.razorpay_key_id, settings.razorpay_key_secret,
            ))
            order = client.order.fetch(txn_id)
            status = order.get("status", "unknown")
            if status == "paid":
                return PaymentStatusResult("paid", txn_id=txn_id, paid_at=datetime.now())
            elif status in ("failed", "cancelled"):
                return PaymentStatusResult("failed", txn_id=txn_id)
            return PaymentStatusResult("pending", txn_id=txn_id)
        except Exception as e:
            logger.error(f"Razorpay status check failed: {e}")
            return PaymentStatusResult("pending", txn_id=txn_id)

    def confirm_payment(self, txn_id: str, customer: Customer,
                        policy: Policy) -> bool:
        """Called on payment webhook / polling confirmation."""
        logger.info(
            f"PAYMENT CONFIRMED | txn={txn_id} | policy={policy.policy_number} "
            f"| customer={customer.name} | Rs.{policy.annual_premium:,.0f} | mock={self.mock}"
        )
        return True

    def get_whatsapp_message(self, result: PaymentLinkResult,
                             language: str = "english") -> str:
        """Format a WhatsApp-ready payment message with UPI link."""
        from agents.layer2_execution.language_utils import get_language_config
        cfg = get_language_config(language)
        lines = [
            f"*{result.customer_name}* — {result.policy_number}",
            f"Amount: Rs.{result.amount:,.0f}",
            f"",
            f"Pay via UPI:",
            f"{result.upi.deep_link}",
            f"",
            f"Pay online: {result.web_link}",
        ]
        if result.autopay:
            lines += ["", f"AutoPay (yearly): {result.autopay.mandate_url}"]
        lines += ["", f"Link valid for {result.expires_at}"]
        return "\n".join(lines)

    # ── Real-mode helpers ──────────────────────────────────────────────────

    def _create_razorpay_order(self, customer: Customer, policy: Policy,
                               txn_id: str) -> Optional[str]:
        try:
            import razorpay
            client = razorpay.Client(auth=(
                settings.razorpay_key_id, settings.razorpay_key_secret,
            ))
            order = client.order.create({
                "amount":   int(policy.annual_premium * 100),
                "currency": "INR",
                "receipt":  txn_id,
                "notes":    {"customer_id": customer.customer_id,
                             "policy_number": policy.policy_number},
            })
            return f"https://rzp.io/i/{order['id']}"
        except Exception as e:
            logger.error(f"Razorpay order creation failed: {e}")
            return None

    def _create_real_mandate(self, customer: Customer, policy: Policy,
                             txn_id: str, stub: AutoPayMandate) -> AutoPayMandate:
        try:
            import razorpay
            client = razorpay.Client(auth=(
                settings.razorpay_key_id, settings.razorpay_key_secret,
            ))
            plan = client.plan.create({
                "period": "yearly", "interval": 1,
                "item": {"name": f"Renewal {policy.policy_number}",
                         "amount": int(policy.annual_premium * 100), "currency": "INR"},
            })
            sub = client.subscription.create({
                "plan_id": plan["id"], "total_count": 5,
                "customer_notify": 1,
                "notes": {"policy_number": policy.policy_number},
            })
            return AutoPayMandate(
                mandate_id=sub["id"], mandate_url=sub["short_url"],
                amount=policy.annual_premium, frequency="yearly",
                policy_number=policy.policy_number,
                status="pending_auth", mock=False,
            )
        except Exception as e:
            logger.error(f"Razorpay mandate creation failed: {e}")
            return stub

    # ── Backward-compat public API used by the test suite ────────────────────

    def build_upi_link(self, policy: Policy) -> UpiDetails:
        """Return a UpiDetails for the given policy (no customer info needed)."""
        txn_id   = f"TXN-{uuid.uuid4().hex[:10].upper()}"
        deep_link = build_upi_deep_link(
            vpa      = MERCHANT_VPA,
            name     = MERCHANT_NAME,
            amount   = policy.annual_premium,
            txn_ref  = txn_id,
            note     = f"Renewal {policy.policy_number}",
        )
        return UpiDetails(
            vpa       = MERCHANT_VPA,
            amount    = policy.annual_premium,
            txn_ref   = txn_id,
            txn_note  = f"Renewal {policy.policy_number}",
            deep_link = deep_link,
            intent_url= deep_link,
        )

    def build_qr_code(self, policy: Policy) -> QrResult:
        """Generate QR PNG for the policy's UPI link."""
        upi = self.build_upi_link(policy)
        return generate_qr_png(upi.deep_link)

    def build_payment_link(self, policy: Policy) -> str:
        """Return a web payment URL for the given policy."""
        txn_id = f"TXN-{uuid.uuid4().hex[:10].upper()}"
        return f"{PAYMENT_BASE_URL}/{txn_id}"

    def create_autopay_mandate(self, policy: Policy) -> dict:
        """Return an AutoPay mandate stub as a plain dict."""
        mandate = build_autopay_mandate(policy.policy_number, policy.annual_premium, mock=True)
        return {
            "mandate_id":  mandate.mandate_id,
            "mandate_url": mandate.mandate_url,
            "amount":      mandate.amount,
            "frequency":   mandate.frequency,
            "status":      "created",
            "mock":        True,
        }
