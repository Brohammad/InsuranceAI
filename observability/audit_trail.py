"""
observability/audit_trail.py
─────────────────────────────
Append-only IRDAI-compliant audit trail for Project RenewAI.

IRDAI requires:
  • All customer communications must be logged with timestamps
  • Sensitive actions (data access, escalation, payment) must be auditable
  • Records must be tamper-evident and retained for 5 years
  • GDPR/DPDP: PII access must be logged

Design:
  • Writes to audit_trail table in SQLite (append-only — no DELETE/UPDATE)
  • Each record carries a sha256 chain hash over (prev_hash + payload)
    so any tampering is detectable
  • AuditCategory covers: COMMUNICATION, PAYMENT, ESCALATION, DATA_ACCESS,
    AGENT_ACTION, SYSTEM, COMPLIANCE
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from loguru import logger

from core.config import settings


# ── Audit categories ──────────────────────────────────────────────────────────

class AuditCategory(str, Enum):
    COMMUNICATION = "communication"   # WhatsApp / Email / Voice sent
    PAYMENT       = "payment"         # Payment link created, status checked
    ESCALATION    = "escalation"      # Case created / resolved
    DATA_ACCESS   = "data_access"     # Customer PII accessed
    AGENT_ACTION  = "agent_action"    # Any agent decision
    SYSTEM        = "system"          # System events (startup, config)
    COMPLIANCE    = "compliance"      # IRDAI / DPDP compliance checks


class AuditOutcome(str, Enum):
    SUCCESS  = "success"
    FAILURE  = "failure"
    BLOCKED  = "blocked"
    WARNING  = "warning"


# ── Audit record ──────────────────────────────────────────────────────────────

@dataclass
class AuditRecord:
    record_id:   str
    category:    str
    action:      str
    outcome:     str
    actor:       str           # agent name or "system"
    journey_id:  Optional[str]
    customer_id: Optional[str]
    policy_no:   Optional[str]
    detail:      str           # JSON blob — structured context
    chain_hash:  str           # sha256(prev_hash + record payload)
    recorded_at: str


# ── DB setup ──────────────────────────────────────────────────────────────────

_CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS audit_trail (
        record_id   TEXT PRIMARY KEY,
        category    TEXT NOT NULL,
        action      TEXT NOT NULL,
        outcome     TEXT NOT NULL,
        actor       TEXT NOT NULL,
        journey_id  TEXT,
        customer_id TEXT,
        policy_no   TEXT,
        detail      TEXT DEFAULT '{}',
        chain_hash  TEXT NOT NULL,
        recorded_at TEXT NOT NULL
    )
"""

_IDX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_audit_cat  ON audit_trail(category)",
    "CREATE INDEX IF NOT EXISTS idx_audit_cust ON audit_trail(customer_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_jour ON audit_trail(journey_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_day  ON audit_trail(DATE(recorded_at))",
]

_GENESIS_HASH = "0" * 64   # chain anchor


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_SQL)
    for idx in _IDX_SQL:
        conn.execute(idx)
    conn.commit()


def _last_hash(conn: sqlite3.Connection) -> str:
    row = conn.execute("""
        SELECT chain_hash FROM audit_trail
        ORDER BY recorded_at DESC LIMIT 1
    """).fetchone()
    return row[0] if row else _GENESIS_HASH


def _compute_hash(prev_hash: str, payload: dict) -> str:
    blob = prev_hash + json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(blob.encode()).hexdigest()


# ── Main audit trail ──────────────────────────────────────────────────────────

class AuditTrail:
    """
    Append-only audit logger with chain-hash integrity.

    Usage:
        audit = AuditTrail()
        audit.log(
            category    = AuditCategory.COMMUNICATION,
            action      = "whatsapp_sent",
            outcome     = AuditOutcome.SUCCESS,
            actor       = "whatsapp_agent",
            journey_id  = "JRN-001",
            customer_id = "CUST-001",
            detail      = {"message_preview": "...", "language": "hi"},
        )
    """

    def __init__(self):
        self._db = str(settings.abs_db_path)
        with sqlite3.connect(self._db) as conn:
            _ensure_table(conn)
        logger.info("AuditTrail ready")

    # ── Core log ──────────────────────────────────────────────────────────────

    def log(
        self,
        category:    AuditCategory,
        action:      str,
        outcome:     AuditOutcome = AuditOutcome.SUCCESS,
        actor:       str = "system",
        journey_id:  Optional[str] = None,
        customer_id: Optional[str] = None,
        policy_no:   Optional[str] = None,
        detail:      Optional[dict[str, Any]] = None,
    ) -> AuditRecord:
        detail = detail or {}
        record_id  = str(uuid.uuid4())
        now        = datetime.now().isoformat()
        detail_str = json.dumps(detail, ensure_ascii=True)

        payload = {
            "record_id":   record_id,
            "category":    category.value if hasattr(category, "value") else str(category),
            "action":      action,
            "outcome":     outcome.value  if hasattr(outcome, "value")  else str(outcome),
            "actor":       actor,
            "journey_id":  journey_id,
            "customer_id": customer_id,
            "policy_no":   policy_no,
            "detail":      detail_str,
            "recorded_at": now,
        }

        with sqlite3.connect(self._db) as conn:
            _ensure_table(conn)
            prev_hash  = _last_hash(conn)
            chain_hash = _compute_hash(prev_hash, payload)

            record = AuditRecord(
                record_id   = record_id,
                category    = payload["category"],
                action      = action,
                outcome     = payload["outcome"],
                actor       = actor,
                journey_id  = journey_id,
                customer_id = customer_id,
                policy_no   = policy_no,
                detail      = detail_str,
                chain_hash  = chain_hash,
                recorded_at = now,
            )
            conn.execute("""
                INSERT INTO audit_trail VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                record.record_id, record.category, record.action,
                record.outcome, record.actor, record.journey_id,
                record.customer_id, record.policy_no,
                record.detail, record.chain_hash, record.recorded_at,
            ))

        logger.debug(
            f"AUDIT | {payload['category']} | {action} | "
            f"{payload['outcome']} | actor={actor}"
        )
        return record

    # ── Convenience wrappers ──────────────────────────────────────────────────

    def log_communication(
        self,
        channel:     str,
        actor:       str,
        outcome:     AuditOutcome,
        journey_id:  Optional[str] = None,
        customer_id: Optional[str] = None,
        policy_no:   Optional[str] = None,
        detail:      Optional[dict] = None,
    ) -> AuditRecord:
        return self.log(
            category    = AuditCategory.COMMUNICATION,
            action      = f"{channel}_sent",
            outcome     = outcome,
            actor       = actor,
            journey_id  = journey_id,
            customer_id = customer_id,
            policy_no   = policy_no,
            detail      = detail,
        )

    def log_payment(
        self,
        action:      str,
        outcome:     AuditOutcome,
        actor:       str = "payment_agent",
        journey_id:  Optional[str] = None,
        customer_id: Optional[str] = None,
        policy_no:   Optional[str] = None,
        detail:      Optional[dict] = None,
    ) -> AuditRecord:
        return self.log(
            category    = AuditCategory.PAYMENT,
            action      = action,
            outcome     = outcome,
            actor       = actor,
            journey_id  = journey_id,
            customer_id = customer_id,
            policy_no   = policy_no,
            detail      = detail,
        )

    def log_escalation(
        self,
        action:      str,
        outcome:     AuditOutcome,
        actor:       str,
        journey_id:  Optional[str] = None,
        customer_id: Optional[str] = None,
        detail:      Optional[dict] = None,
    ) -> AuditRecord:
        return self.log(
            category    = AuditCategory.ESCALATION,
            action      = action,
            outcome     = outcome,
            actor       = actor,
            journey_id  = journey_id,
            customer_id = customer_id,
            detail      = detail,
        )

    # ── Query + verification ──────────────────────────────────────────────────

    def get_journey_trail(self, journey_id: str) -> list[AuditRecord]:
        with sqlite3.connect(self._db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM audit_trail
                WHERE journey_id = ?
                ORDER BY recorded_at ASC
            """, (journey_id,)).fetchall()
        return [AuditRecord(**dict(r)) for r in rows]

    def get_customer_trail(self, customer_id: str, limit: int = 100) -> list[AuditRecord]:
        with sqlite3.connect(self._db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(f"""
                SELECT * FROM audit_trail
                WHERE customer_id = ?
                ORDER BY recorded_at DESC
                LIMIT {limit}
            """, (customer_id,)).fetchall()
        return [AuditRecord(**dict(r)) for r in rows]

    def verify_chain(self, limit: int = 1000) -> dict[str, Any]:
        """
        Walk the chain and detect any hash mismatch.
        Returns {"valid": True/False, "errors": [...], "checked": N}
        """
        with sqlite3.connect(self._db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(f"""
                SELECT * FROM audit_trail
                ORDER BY recorded_at ASC
                LIMIT {limit}
            """).fetchall()

        errors = []
        prev_hash = _GENESIS_HASH

        for row in rows:
            r = dict(row)
            payload = {
                "record_id":   r["record_id"],
                "category":    r["category"],
                "action":      r["action"],
                "outcome":     r["outcome"],
                "actor":       r["actor"],
                "journey_id":  r["journey_id"],
                "customer_id": r["customer_id"],
                "policy_no":   r["policy_no"],
                "detail":      r["detail"],
                "recorded_at": r["recorded_at"],
            }
            expected = _compute_hash(prev_hash, payload)
            if expected != r["chain_hash"]:
                errors.append({
                    "record_id": r["record_id"],
                    "expected":  expected[:16] + "...",
                    "got":       r["chain_hash"][:16] + "...",
                })
            prev_hash = r["chain_hash"]

        return {
            "valid":   len(errors) == 0,
            "checked": len(rows),
            "errors":  errors,
        }

    def daily_count(self, day: Optional[str] = None) -> dict[str, int]:
        """Count of audit records by category for a given day."""
        from datetime import date as _date
        day = day or _date.today().isoformat()
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute("""
                SELECT category, COUNT(*) FROM audit_trail
                WHERE DATE(recorded_at) = ?
                GROUP BY category
            """, (day,)).fetchall()
        return {r[0]: r[1] for r in rows}
