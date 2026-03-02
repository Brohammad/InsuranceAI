"""
integrations/irdai_stub.py
───────────────────────────
IRDAI (Insurance Regulatory and Development Authority of India) Reporting Stub

IRDAI mandates:
  • All customer communications must be logged (Regulation 8)
  • Grievance acknowledgement within 3 working days
  • Grievance resolution within 14 days
  • Annual returns on lapse rates, persistency, mis-selling complaints
  • Policyholder Protection regulations compliance

This stub covers:
  • report_communication()     — log communication to IRDAI portal (mock)
  • file_grievance()           — submit customer grievance to IRDAI
  • acknowledge_grievance()    — send 3-day ack
  • resolve_grievance()        — close grievance with resolution
  • get_persistency_stats()    — return persistency ratio (13M, 25M, 37M, 61M)
  • check_call_compliance()    — verify call is within 8AM-8PM IST window
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, date
from typing import Any, Optional

from loguru import logger

from core.config import settings


# ── IST timezone ──────────────────────────────────────────────────────────────

IST = timezone(timedelta(hours=5, minutes=30))
CALL_START = 8   # 8 AM IST
CALL_END   = 20  # 8 PM IST


# ── Response models ────────────────────────────────────────────────────────────

@dataclass
class IrdaiGrievance:
    grievance_id:   str
    policy_number:  str
    customer_id:    str
    category:       str
    description:    str
    filed_at:       str
    ack_deadline:   str   # +3 working days
    resolve_deadline:str  # +14 calendar days
    status:         str   # "filed" | "acknowledged" | "resolved"
    mock:           bool = True


@dataclass
class IrdaiCommunicationLog:
    log_id:       str
    policy_number:str
    channel:      str
    direction:    str
    language:     str
    outcome:      str
    logged_at:    str
    mock:         bool = True


@dataclass
class PersistencyStats:
    policy_number: str
    ratio_13m:     float   # % of policies reaching 13th month
    ratio_25m:     float
    ratio_37m:     float
    ratio_61m:     float
    calculated_on: str
    mock:          bool = True


# ── Compliance check ───────────────────────────────────────────────────────────

def check_call_compliance() -> dict[str, Any]:
    """
    Check if current IST time is within IRDAI-mandated 8AM-8PM call window.
    Returns {"allowed": bool, "current_ist": str, "next_window": str}
    """
    now_ist = datetime.now(IST)
    allowed = CALL_START <= now_ist.hour < CALL_END

    if allowed:
        next_window = "Now"
    else:
        if now_ist.hour < CALL_START:
            next_open = now_ist.replace(hour=CALL_START, minute=0, second=0)
        else:
            next_open = (now_ist + timedelta(days=1)).replace(
                hour=CALL_START, minute=0, second=0
            )
        mins_until = int((next_open - now_ist).total_seconds() / 60)
        next_window = f"in {mins_until // 60}h {mins_until % 60}m ({next_open.strftime('%I:%M %p IST')})"

    return {
        "allowed":     allowed,
        "current_ist": now_ist.strftime("%H:%M IST"),
        "next_window": next_window,
    }


def _add_working_days(start: datetime, days: int) -> datetime:
    """Add N working days (Mon-Fri) to a datetime."""
    current = start
    added   = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:   # Mon-Fri
            added += 1
    return current


# ── IRDAI stub ─────────────────────────────────────────────────────────────────

class IrdaiStub:
    """IRDAI regulatory reporting stub."""

    def __init__(self):
        self.mock = settings.mock_delivery
        logger.info(f"IrdaiStub ready | mock={self.mock}")

    def report_communication(
        self,
        policy_number: str,
        channel:       str,
        direction:     str = "outbound",
        language:      str = "en",
        outcome:       str = "delivered",
    ) -> IrdaiCommunicationLog:
        """Log a customer communication to the IRDAI portal."""
        log = IrdaiCommunicationLog(
            log_id        = str(uuid.uuid4()),
            policy_number = policy_number,
            channel       = channel,
            direction     = direction,
            language      = language,
            outcome       = outcome,
            logged_at     = datetime.now().isoformat(),
            mock          = self.mock,
        )
        if self.mock:
            logger.info(
                f"[IRDAI STUB] report_communication | {policy_number} | "
                f"{channel}/{direction} | {outcome}"
            )
            return log
        raise NotImplementedError("Real IRDAI portal API not configured")

    def file_grievance(
        self,
        policy_number:  str,
        customer_id:    str,
        category:       str,
        description:    str,
    ) -> IrdaiGrievance:
        """
        File a customer grievance.
        category: "mis_selling" | "claim_rejection" | "service_failure" |
                  "premium_dispute" | "cancellation" | "other"
        """
        now = datetime.now()
        grievance = IrdaiGrievance(
            grievance_id     = f"GRV-{uuid.uuid4().hex[:8].upper()}",
            policy_number    = policy_number,
            customer_id      = customer_id,
            category         = category,
            description      = description[:500],
            filed_at         = now.isoformat(),
            ack_deadline     = _add_working_days(now, 3).strftime("%Y-%m-%d"),
            resolve_deadline = (now + timedelta(days=14)).strftime("%Y-%m-%d"),
            status           = "filed",
            mock             = self.mock,
        )
        if self.mock:
            logger.warning(
                f"[IRDAI STUB] file_grievance | {policy_number} | "
                f"{category} | ack by {grievance.ack_deadline}"
            )
            return grievance
        raise NotImplementedError("Real IRDAI grievance portal not configured")

    def acknowledge_grievance(self, grievance_id: str) -> dict[str, Any]:
        """Send 3-day acknowledgement for a grievance."""
        if self.mock:
            logger.info(f"[IRDAI STUB] acknowledge_grievance | {grievance_id}")
            return {
                "grievance_id": grievance_id,
                "acknowledged": True,
                "ack_ref":      f"ACK-{uuid.uuid4().hex[:6].upper()}",
                "ack_at":       datetime.now().isoformat(),
                "mock":         True,
            }
        raise NotImplementedError("Real IRDAI ack API not configured")

    def resolve_grievance(
        self,
        grievance_id: str,
        resolution:   str,
        resolved_by:  str = "renewai_system",
    ) -> dict[str, Any]:
        """Close a grievance with resolution note."""
        if self.mock:
            logger.info(
                f"[IRDAI STUB] resolve_grievance | {grievance_id} | "
                f"by {resolved_by}"
            )
            return {
                "grievance_id": grievance_id,
                "resolved":     True,
                "resolution":   resolution[:300],
                "resolved_by":  resolved_by,
                "resolved_at":  datetime.now().isoformat(),
                "mock":         True,
            }
        raise NotImplementedError("Real IRDAI resolution API not configured")

    def get_persistency_stats(self, policy_number: str) -> PersistencyStats:
        """Return persistency ratios for the policy cohort."""
        if self.mock:
            logger.info(f"[IRDAI STUB] get_persistency_stats | {policy_number}")
            return PersistencyStats(
                policy_number  = policy_number,
                ratio_13m      = 87.4,
                ratio_25m      = 82.1,
                ratio_37m      = 78.6,
                ratio_61m      = 71.2,
                calculated_on  = date.today().isoformat(),
                mock           = True,
            )
        raise NotImplementedError("Real IRDAI persistency API not configured")

    @staticmethod
    def check_call_window() -> dict[str, Any]:
        """Check IRDAI 8AM-8PM IST call compliance window."""
        return check_call_compliance()
