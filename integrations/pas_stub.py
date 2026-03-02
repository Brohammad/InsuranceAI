"""
integrations/pas_stub.py
──────────────────────────
Policy Administration System (PAS) Integration Stub

In production: REST/SOAP calls to the core insurance platform
(e.g. DuckCreek, Majesco, or custom in-house PAS).
In mock mode: returns realistic stub data.

Covers:
  • get_policy()            — fetch full policy record
  • update_renewal_status() — mark policy as renewed / lapsed / grace
  • issue_endorsement()     — issue a policy endorsement
  • apply_grace_period()    — extend grace period for a policy
  • get_payment_history()   — pull premium payment history
  • trigger_lapse()         — mark policy as lapsed after grace period
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from loguru import logger

from core.config import settings


# ── Response models ────────────────────────────────────────────────────────────

@dataclass
class PasPolicy:
    policy_number:    str
    customer_id:      str
    product_name:     str
    status:           str
    renewal_due_date: str
    annual_premium:   float
    sum_assured:      float
    grace_period_days:int
    has_auto_debit:   bool
    mock:             bool = True


@dataclass
class PasRenewalUpdate:
    policy_number: str
    old_status:    str
    new_status:    str
    updated_at:    str
    ref_id:        str
    mock:          bool = True


@dataclass
class PasEndorsement:
    endorsement_id: str
    policy_number:  str
    type:           str
    description:    str
    issued_at:      str
    mock:           bool = True


@dataclass
class PasPaymentRecord:
    payment_id:  str
    policy_number:str
    amount:      float
    paid_on:     str
    mode:        str
    status:      str
    mock:        bool = True


# ── PAS stub ───────────────────────────────────────────────────────────────────

class PasStub:
    """Policy Administration System stub client."""

    def __init__(self):
        self.mock = settings.mock_delivery
        logger.info(f"PasStub ready | mock={self.mock}")

    def get_policy(self, policy_number: str) -> Optional[PasPolicy]:
        """Fetch full policy record from PAS."""
        if self.mock:
            logger.info(f"[PAS STUB] get_policy | {policy_number}")
            return PasPolicy(
                policy_number    = policy_number,
                customer_id      = "CUST-MOCK",
                product_name     = "Term Plan 1 Cr",
                status           = "active",
                renewal_due_date = (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d"),
                annual_premium   = 25000.0,
                sum_assured      = 10_000_000.0,
                grace_period_days= 30,
                has_auto_debit   = False,
                mock             = True,
            )
        raise NotImplementedError("Real PAS integration not configured")

    def update_renewal_status(
        self,
        policy_number: str,
        new_status:    str,
        notes:         str = "",
    ) -> PasRenewalUpdate:
        """
        Update policy status in PAS.
        new_status: "renewed" | "lapsed" | "grace_period" | "cancelled"
        """
        valid = {"renewed", "lapsed", "grace_period", "cancelled", "active"}
        if new_status not in valid:
            raise ValueError(f"Invalid PAS status: {new_status}. Must be one of {valid}")

        if self.mock:
            update = PasRenewalUpdate(
                policy_number = policy_number,
                old_status    = "active",
                new_status    = new_status,
                updated_at    = datetime.now().isoformat(),
                ref_id        = f"PAS-REF-{uuid.uuid4().hex[:8].upper()}",
                mock          = True,
            )
            logger.info(
                f"[PAS STUB] update_renewal_status | {policy_number} → {new_status}"
            )
            return update
        raise NotImplementedError("Real PAS status update not configured")

    def issue_endorsement(
        self,
        policy_number: str,
        endo_type:     str,
        description:   str,
    ) -> PasEndorsement:
        """Issue a policy endorsement (e.g. address change, nominee update)."""
        if self.mock:
            endo = PasEndorsement(
                endorsement_id = f"ENDO-{uuid.uuid4().hex[:8].upper()}",
                policy_number  = policy_number,
                type           = endo_type,
                description    = description,
                issued_at      = datetime.now().isoformat(),
                mock           = True,
            )
            logger.info(f"[PAS STUB] issue_endorsement | {policy_number} | {endo_type}")
            return endo
        raise NotImplementedError("Real PAS endorsement not configured")

    def apply_grace_period(
        self,
        policy_number:    str,
        extension_days:   int = 30,
    ) -> dict[str, Any]:
        """Extend grace period for a policy (max 90 days per IRDAI regulations)."""
        if extension_days > 90:
            raise ValueError("Grace period extension cannot exceed 90 days (IRDAI limit)")
        if self.mock:
            new_deadline = (datetime.now() + timedelta(days=extension_days)).strftime("%Y-%m-%d")
            logger.info(
                f"[PAS STUB] apply_grace_period | {policy_number} | +{extension_days}d → {new_deadline}"
            )
            return {
                "policy_number":  policy_number,
                "extension_days": extension_days,
                "new_deadline":   new_deadline,
                "approved":       True,
                "ref_id":         f"GRACE-{uuid.uuid4().hex[:8].upper()}",
                "mock":           True,
            }
        raise NotImplementedError("Real PAS grace period API not configured")

    def get_payment_history(
        self,
        policy_number: str,
        limit:         int = 5,
    ) -> list[PasPaymentRecord]:
        """Pull last N premium payment records."""
        if self.mock:
            logger.info(f"[PAS STUB] get_payment_history | {policy_number}")
            return [
                PasPaymentRecord(
                    payment_id    = f"PAY-{i:03d}",
                    policy_number = policy_number,
                    amount        = 25000.0,
                    paid_on       = (datetime.now() - timedelta(days=365 * i)).strftime("%Y-%m-%d"),
                    mode          = "upi",
                    status        = "success",
                    mock          = True,
                )
                for i in range(1, min(limit, 5) + 1)
            ]
        raise NotImplementedError("Real PAS payment history API not configured")

    def trigger_lapse(self, policy_number: str, reason: str = "non_payment") -> bool:
        """Mark a policy as lapsed after grace period expiry."""
        if self.mock:
            logger.warning(f"[PAS STUB] trigger_lapse | {policy_number} | reason={reason}")
            return True
        raise NotImplementedError("Real PAS lapse trigger not configured")
