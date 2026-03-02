"""
integrations/payment_gw_stub.py
─────────────────────────────────
Payment Gateway Integration Stub — Razorpay Webhook Handler

Covers:
  • parse_webhook()          — verify Razorpay webhook signature + parse event
  • handle_payment_captured()— update DB on successful payment
  • handle_payment_failed()  — log failure + trigger retry workflow
  • handle_refund_created()  — log refund event
  • create_payment_link()    — thin wrapper over Razorpay API (real mode)
  • verify_payment()         — verify payment status via Razorpay API

Webhook events supported:
  payment.captured | payment.failed | refund.created | order.paid
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from loguru import logger

from core.config import settings


# ── Webhook event types ────────────────────────────────────────────────────────

WEBHOOK_EVENTS = {
    "payment.captured",
    "payment.failed",
    "refund.created",
    "order.paid",
}


# ── Response models ────────────────────────────────────────────────────────────

@dataclass
class WebhookResult:
    event:        str
    payment_id:   str
    order_id:     str
    amount_paise: int
    amount_inr:   float
    status:       str
    policy_number:Optional[str]
    notes:        dict[str, Any]
    received_at:  str
    mock:         bool = True


@dataclass
class PaymentVerification:
    payment_id: str
    order_id:   str
    status:     str   # "captured" | "failed" | "pending"
    amount_inr: float
    method:     str   # "upi" | "netbanking" | "card"
    verified:   bool
    mock:       bool = True


# ── Signature verification ────────────────────────────────────────────────────

def verify_razorpay_signature(
    payload_body: bytes,
    received_sig: str,
    webhook_secret: str,
) -> bool:
    """
    Verify Razorpay webhook HMAC-SHA256 signature.
    Razorpay signs: HMAC_SHA256(webhook_secret, raw_body)
    """
    expected = hmac.new(
        webhook_secret.encode(),
        payload_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received_sig)


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _mark_payment_received(db_path: str, policy_number: str, payment_id: str) -> None:
    """Update renewal_journeys to mark payment received."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                UPDATE renewal_journeys
                SET payment_received    = 1,
                    payment_received_at = ?,
                    status              = 'renewed'
                WHERE policy_number = ?
                  AND payment_received  = 0
            """, (datetime.now().isoformat(), policy_number))
            conn.execute("""
                UPDATE policies SET status = 'active' WHERE policy_number = ?
            """, (policy_number,))
    except Exception as exc:
        logger.error(f"DB update failed for payment {payment_id}: {exc}")


# ── Payment gateway stub ───────────────────────────────────────────────────────

class PaymentGatewayStub:
    """
    Razorpay payment gateway stub.
    Handles inbound webhooks and exposes verification helpers.
    """

    def __init__(self):
        self.mock       = settings.mock_delivery
        self._db        = str(settings.abs_db_path)
        self._key_id    = settings.razorpay_key_id
        self._key_secret= settings.razorpay_key_secret
        logger.info(f"PaymentGatewayStub ready | mock={self.mock}")

    def parse_webhook(
        self,
        body:       bytes,
        signature:  str,
        secret:     str = "",
    ) -> WebhookResult:
        """
        Parse and validate an inbound Razorpay webhook.
        In mock mode: skip signature check and parse body directly.
        """
        secret = secret or self._key_secret

        if not self.mock:
            if not verify_razorpay_signature(body, signature, secret):
                logger.error("Razorpay webhook signature mismatch — rejected")
                raise ValueError("Invalid Razorpay webhook signature")

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid webhook JSON: {e}")

        event   = payload.get("event", "unknown")
        entity  = payload.get("payload", {}).get("payment", {}).get("entity", {})

        amount_paise = entity.get("amount", 0)
        result = WebhookResult(
            event         = event,
            payment_id    = entity.get("id", f"pay_{uuid.uuid4().hex[:14]}"),
            order_id      = entity.get("order_id", ""),
            amount_paise  = amount_paise,
            amount_inr    = round(amount_paise / 100, 2),
            status        = entity.get("status", "unknown"),
            policy_number = entity.get("notes", {}).get("policy_number"),
            notes         = entity.get("notes", {}),
            received_at   = datetime.now().isoformat(),
            mock          = self.mock,
        )

        logger.info(
            f"[PAYMENT GW] webhook | {event} | {result.payment_id} | "
            f"₹{result.amount_inr} | status={result.status}"
        )

        # Handle event
        if event == "payment.captured":
            self._on_payment_captured(result)
        elif event == "payment.failed":
            self._on_payment_failed(result)
        elif event == "refund.created":
            self._on_refund_created(result)

        return result

    def verify_payment(self, payment_id: str) -> PaymentVerification:
        """Check payment status via Razorpay Fetch Payment API."""
        if self.mock:
            logger.info(f"[PAYMENT GW STUB] verify_payment | {payment_id}")
            return PaymentVerification(
                payment_id = payment_id,
                order_id   = f"order_{uuid.uuid4().hex[:14]}",
                status     = "captured",
                amount_inr = 25000.0,
                method     = "upi",
                verified   = True,
                mock       = True,
            )
        # Real mode: call Razorpay API
        try:
            import razorpay
            client = razorpay.Client(auth=(self._key_id, self._key_secret))
            payment = client.payment.fetch(payment_id)
            return PaymentVerification(
                payment_id = payment["id"],
                order_id   = payment.get("order_id", ""),
                status     = payment.get("status", "unknown"),
                amount_inr = payment.get("amount", 0) / 100,
                method     = payment.get("method", "unknown"),
                verified   = payment.get("status") == "captured",
                mock       = False,
            )
        except Exception as e:
            logger.error(f"Razorpay verify failed: {e}")
            raise

    # ── Internal event handlers ───────────────────────────────────────────────

    def _on_payment_captured(self, result: WebhookResult) -> None:
        logger.info(
            f"✅ Payment captured: {result.payment_id} | "
            f"₹{result.amount_inr} | policy={result.policy_number}"
        )
        if result.policy_number:
            _mark_payment_received(self._db, result.policy_number, result.payment_id)

    def _on_payment_failed(self, result: WebhookResult) -> None:
        logger.warning(
            f"❌ Payment failed: {result.payment_id} | "
            f"policy={result.policy_number} | ₹{result.amount_inr}"
        )
        # In production: trigger retry journey step

    def _on_refund_created(self, result: WebhookResult) -> None:
        logger.info(
            f"🔄 Refund created: {result.payment_id} | ₹{result.amount_inr}"
        )
