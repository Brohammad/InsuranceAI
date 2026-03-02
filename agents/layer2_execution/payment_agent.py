"""
agents/layer2_execution/payment_agent.py
──────────────────────────────────────────
Payment Agent — Layer 2

Generates payment links (UPI / web), tracks payment status,
and signals the Orchestrator to STOP the journey when paid.

MOCK MODE: Returns a fake payment record. Randomly marks
           30% of policies as "paid" to test journey stop logic.

REAL MODE: Integrates with a payment gateway (Razorpay / PayU / 
           Paytm) to create real payment orders and webhooks.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime

from loguru import logger

from core.config import settings
from core.models import Customer, Policy
from agents.layer2_execution.mock_utils import mock_payment_link


# ── Output ────────────────────────────────────────────────────────────────────

@dataclass
class PaymentLinkResult:
    txn_id:         str
    upi_link:       str
    web_link:       str
    qr_data:        str
    amount:         float
    status:         str         # "pending" | "paid" | "failed" | "expired"
    created_at:     datetime
    mock:           bool = True


@dataclass
class PaymentStatusResult:
    txn_id:         str
    status:         str
    paid_at:        datetime | None
    amount_paid:    float | None
    payment_method: str | None  # "upi" | "card" | "netbanking" | "wallet"


# ── Agent ─────────────────────────────────────────────────────────────────────

class PaymentAgent:
    """Generates payment links and tracks payment status."""

    MOCK_PAID_RATE = 0.30   # 30% of mock policies are "already paid"

    def __init__(self):
        self.mock = settings.mock_delivery
        logger.info(f"PaymentAgent ready | mock={self.mock}")

    def create_link(
        self,
        customer: Customer,
        policy:   Policy,
    ) -> PaymentLinkResult:
        """Create a new payment link for a policy renewal."""
        logger.debug(f"Creating payment link for {policy.policy_number} | ₹{policy.annual_premium:,.0f}")

        if self.mock:
            data = mock_payment_link(policy.policy_number, policy.annual_premium)
            return PaymentLinkResult(
                txn_id         = data["txn_id"],
                upi_link       = data["upi_link"],
                web_link       = data["web_link"],
                qr_data        = data["qr_data"],
                amount         = policy.annual_premium,
                status         = "pending",
                created_at     = datetime.now(),
                mock           = True,
            )

        # ── Real mode: Razorpay example ──────────────────────────────────
        try:
            import razorpay
            client = razorpay.Client(auth=("YOUR_KEY_ID", "YOUR_KEY_SECRET"))
            order = client.order.create({
                "amount":   int(policy.annual_premium * 100),   # paise
                "currency": "INR",
                "receipt":  policy.policy_number,
                "notes":    {"customer_id": customer.customer_id},
            })
            return PaymentLinkResult(
                txn_id     = order["id"],
                upi_link   = f"upi://pay?pa=renewai@razorpay&am={policy.annual_premium:.0f}&tn={order['id']}",
                web_link   = f"https://rzp.io/i/{order['id']}",
                qr_data    = f"[QR:{order['id']}]",
                amount     = policy.annual_premium,
                status     = "pending",
                created_at = datetime.now(),
                mock       = False,
            )
        except Exception as e:
            logger.error(f"Payment gateway error: {e}")
            data = mock_payment_link(policy.policy_number, policy.annual_premium)
            return PaymentLinkResult(**data, amount=policy.annual_premium, status="pending",
                                     created_at=datetime.now(), mock=True)

    def check_status(self, txn_id: str) -> PaymentStatusResult:
        """
        Poll payment status.
        MOCK: 30% chance of returning 'paid' to simulate payment receipt.
        """
        if self.mock:
            paid = random.random() < self.MOCK_PAID_RATE
            methods = ["upi", "card", "netbanking", "wallet"]
            return PaymentStatusResult(
                txn_id         = txn_id,
                status         = "paid" if paid else "pending",
                paid_at        = datetime.now() if paid else None,
                amount_paid    = None,
                payment_method = random.choice(methods) if paid else None,
            )

        # Real: query your payment gateway
        raise NotImplementedError("Real payment status check not yet wired")

    def confirm_payment(
        self,
        txn_id:   str,
        customer: Customer,
        policy:   Policy,
    ) -> bool:
        """
        Called when payment webhook fires.
        Returns True if confirmed, triggers journey stop.
        In mock mode: just logs and returns True.
        """
        logger.info(
            f"Payment CONFIRMED | txn={txn_id} | {policy.policy_number} | {customer.name} "
            f"| ₹{policy.annual_premium:,.0f} | mock={self.mock}"
        )
        return True
