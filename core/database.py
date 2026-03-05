"""
core/database.py
────────────────
SQLite database layer for Project RenewAI.
Creates schema on first run; provides typed query helpers used by all agents.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Generator, Optional

from loguru import logger

from core.config import settings
from core.models import (
    Customer,
    EscalationCase,
    Interaction,
    Language,
    Channel,
    Policy,
    PolicyStatus,
    ProductType,
    RenewalJourney,
    JourneyStatus,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_dict(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict:
    return dict(zip([c[0] for c in cursor.description], row))


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Context manager that yields a DB connection and commits/rolls back."""
    db_path = settings.abs_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id         TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    age                 INTEGER,
    gender              TEXT,
    city                TEXT,
    state               TEXT,
    preferred_language  TEXT,
    preferred_channel   TEXT,
    preferred_call_time TEXT,
    email               TEXT,
    phone               TEXT,
    whatsapp_number     TEXT,
    occupation          TEXT,
    is_on_dnd           INTEGER DEFAULT 0,
    created_at          TEXT
);

CREATE TABLE IF NOT EXISTS policies (
    policy_number       TEXT PRIMARY KEY,
    customer_id         TEXT NOT NULL,
    product_type        TEXT,
    product_name        TEXT,
    sum_assured         REAL,
    annual_premium      REAL,
    policy_start_date   TEXT,
    renewal_due_date    TEXT,
    tenure_years        INTEGER,
    years_completed     INTEGER,
    status              TEXT DEFAULT 'active',
    payment_mode        TEXT DEFAULT 'annual',
    has_auto_debit      INTEGER DEFAULT 0,
    payment_history     TEXT DEFAULT '[]',
    last_payment_date   TEXT,
    grace_period_days   INTEGER DEFAULT 30,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE IF NOT EXISTS renewal_journeys (
    journey_id          TEXT PRIMARY KEY,
    policy_number       TEXT NOT NULL,
    customer_id         TEXT NOT NULL,
    status              TEXT DEFAULT 'not_started',
    segment             TEXT,
    lapse_score         INTEGER,
    channel_sequence    TEXT DEFAULT '[]',
    steps               TEXT DEFAULT '[]',
    current_step_index  INTEGER DEFAULT 0,
    payment_received    INTEGER DEFAULT 0,
    payment_received_at TEXT,
    escalated           INTEGER DEFAULT 0,
    escalation_reason   TEXT,
    created_at          TEXT,
    updated_at          TEXT,
    FOREIGN KEY (policy_number) REFERENCES policies(policy_number)
);

CREATE TABLE IF NOT EXISTS interactions (
    interaction_id   TEXT PRIMARY KEY,
    journey_id       TEXT,
    policy_number    TEXT,
    customer_id      TEXT,
    channel          TEXT,
    direction        TEXT,
    message_content  TEXT,
    language         TEXT,
    sent_at          TEXT,
    outcome          TEXT,
    sentiment_score  REAL,
    quality_score    REAL,
    critique_passed  INTEGER,
    safety_flags     TEXT DEFAULT '[]',
    raw_response     TEXT,
    FOREIGN KEY (journey_id) REFERENCES renewal_journeys(journey_id)
);

CREATE TABLE IF NOT EXISTS escalation_cases (
    case_id          TEXT PRIMARY KEY,
    journey_id       TEXT,
    policy_number    TEXT,
    customer_id      TEXT,
    reason           TEXT,
    priority         TEXT,
    briefing_note    TEXT,
    assigned_to      TEXT,
    resolved         INTEGER DEFAULT 0,
    resolved_at      TEXT,
    resolution_note  TEXT,
    created_at       TEXT,
    sla_deadline     TEXT,
    FOREIGN KEY (journey_id) REFERENCES renewal_journeys(journey_id)
);

CREATE INDEX IF NOT EXISTS idx_policies_customer     ON policies(customer_id);
CREATE INDEX IF NOT EXISTS idx_policies_renewal_date ON policies(renewal_due_date);
CREATE INDEX IF NOT EXISTS idx_journeys_policy       ON renewal_journeys(policy_number);
CREATE INDEX IF NOT EXISTS idx_journeys_status       ON renewal_journeys(status);
CREATE INDEX IF NOT EXISTS idx_interactions_journey  ON interactions(journey_id);
CREATE INDEX IF NOT EXISTS idx_escalations_priority  ON escalation_cases(priority);

CREATE TABLE IF NOT EXISTS quality_scores (
    score_id         TEXT PRIMARY KEY,
    journey_id       TEXT,
    policy_number    TEXT,
    customer_name    TEXT,
    channel          TEXT,
    critique_score   REAL,
    compliance_score REAL,
    safety_score     REAL,
    sentiment_score  REAL,
    total_score      REAL,
    grade            TEXT,
    summary          TEXT,
    strengths        TEXT,
    improvements     TEXT,
    scored_at        TEXT
);

CREATE TABLE IF NOT EXISTS ab_test_results (
    test_id          TEXT PRIMARY KEY,
    variant_type     TEXT,
    winner           TEXT,
    runner_up        TEXT,
    winner_conv_rate REAL,
    runner_up_rate   REAL,
    lift_pct         REAL,
    significant      INTEGER,
    sample_size      INTEGER,
    recommendation   TEXT,
    run_at           TEXT
);
"""


def init_db() -> None:
    """Create all tables and indexes (idempotent)."""
    with get_connection() as conn:
        conn.executescript(SCHEMA_SQL)
    logger.info(f"Database initialised at {settings.abs_db_path}")


# ── Customer helpers ──────────────────────────────────────────────────────────

def upsert_customer(customer: Customer) -> None:
    sql = """
    INSERT INTO customers VALUES (
        :customer_id, :name, :age, :gender, :city, :state,
        :preferred_language, :preferred_channel, :preferred_call_time,
        :email, :phone, :whatsapp_number, :occupation, :is_on_dnd, :created_at
    )
    ON CONFLICT(customer_id) DO UPDATE SET
        name=excluded.name, email=excluded.email, phone=excluded.phone,
        preferred_language=excluded.preferred_language,
        preferred_channel=excluded.preferred_channel,
        preferred_call_time=excluded.preferred_call_time,
        is_on_dnd=excluded.is_on_dnd
    """
    with get_connection() as conn:
        conn.execute(sql, {
            "customer_id":         customer.customer_id,
            "name":                customer.name,
            "age":                 customer.age,
            "gender":              customer.gender,
            "city":                customer.city,
            "state":               customer.state,
            "preferred_language":  customer.preferred_language.value,
            "preferred_channel":   customer.preferred_channel.value,
            "preferred_call_time": customer.preferred_call_time,
            "email":               customer.email,
            "phone":               customer.phone,
            "whatsapp_number":     customer.whatsapp_number,
            "occupation":          customer.occupation,
            "is_on_dnd":           int(customer.is_on_dnd),
            "created_at":          customer.created_at.isoformat(),
        })


def get_customer(customer_id: str) -> Optional[Customer]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["is_on_dnd"] = bool(d["is_on_dnd"])
    d["preferred_language"] = Language(d["preferred_language"])
    d["preferred_channel"]  = Channel(d["preferred_channel"])
    d["created_at"]         = datetime.fromisoformat(d["created_at"])
    return Customer(**d)


# ── Policy helpers ────────────────────────────────────────────────────────────

def upsert_policy(policy: Policy) -> None:
    sql = """
    INSERT INTO policies VALUES (
        :policy_number, :customer_id, :product_type, :product_name,
        :sum_assured, :annual_premium, :policy_start_date, :renewal_due_date,
        :tenure_years, :years_completed, :status, :payment_mode,
        :has_auto_debit, :payment_history, :last_payment_date, :grace_period_days
    )
    ON CONFLICT(policy_number) DO UPDATE SET
        status=excluded.status,
        renewal_due_date=excluded.renewal_due_date,
        years_completed=excluded.years_completed,
        payment_history=excluded.payment_history,
        last_payment_date=excluded.last_payment_date,
        has_auto_debit=excluded.has_auto_debit
    """
    with get_connection() as conn:
        conn.execute(sql, {
            "policy_number":     policy.policy_number,
            "customer_id":       policy.customer_id,
            "product_type":      policy.product_type.value,
            "product_name":      policy.product_name,
            "sum_assured":       policy.sum_assured,
            "annual_premium":    policy.annual_premium,
            "policy_start_date": policy.policy_start_date.isoformat(),
            "renewal_due_date":  policy.renewal_due_date.isoformat(),
            "tenure_years":      policy.tenure_years,
            "years_completed":   policy.years_completed,
            "status":            policy.status.value,
            "payment_mode":      policy.payment_mode,
            "has_auto_debit":    int(policy.has_auto_debit),
            "payment_history":   json.dumps(policy.payment_history),
            "last_payment_date": policy.last_payment_date.isoformat() if policy.last_payment_date else None,
            "grace_period_days": policy.grace_period_days,
        })


def get_policy(policy_number: str) -> Optional[Policy]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM policies WHERE policy_number = ?", (policy_number,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["product_type"]      = ProductType(d["product_type"])
    d["status"]            = PolicyStatus(d["status"])
    d["has_auto_debit"]    = bool(d["has_auto_debit"])
    d["payment_history"]   = json.loads(d["payment_history"])
    d["policy_start_date"] = date.fromisoformat(d["policy_start_date"])
    d["renewal_due_date"]  = date.fromisoformat(d["renewal_due_date"])
    if d["last_payment_date"]:
        d["last_payment_date"] = date.fromisoformat(d["last_payment_date"])
    return Policy(**d)


def get_policies_due_within_days(days: int) -> list[Policy]:
    """Return active policies whose renewal_due_date is within the next N days."""
    today = date.today().isoformat()
    from datetime import timedelta
    future = (date.today() + timedelta(days=days)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM policies
               WHERE status = 'active'
               AND renewal_due_date BETWEEN ? AND ?
               ORDER BY renewal_due_date""",
            (today, future),
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["product_type"]      = ProductType(d["product_type"])
        d["status"]            = PolicyStatus(d["status"])
        d["has_auto_debit"]    = bool(d["has_auto_debit"])
        d["payment_history"]   = json.loads(d["payment_history"])
        d["policy_start_date"] = date.fromisoformat(d["policy_start_date"])
        d["renewal_due_date"]  = date.fromisoformat(d["renewal_due_date"])
        if d["last_payment_date"]:
            d["last_payment_date"] = date.fromisoformat(d["last_payment_date"])
        result.append(Policy(**d))
    return result


# ── Journey helpers ───────────────────────────────────────────────────────────

def create_journey(journey: RenewalJourney) -> None:
    sql = """
    INSERT INTO renewal_journeys VALUES (
        :journey_id, :policy_number, :customer_id, :status,
        :segment, :lapse_score, :channel_sequence, :steps,
        :current_step_index, :payment_received, :payment_received_at,
        :escalated, :escalation_reason, :created_at, :updated_at
    )
    """
    with get_connection() as conn:
        conn.execute(sql, {
            "journey_id":          journey.journey_id,
            "policy_number":       journey.policy_number,
            "customer_id":         journey.customer_id,
            "status":              journey.status.value,
            "segment":             journey.segment.value if journey.segment else None,
            "lapse_score":         journey.lapse_score,
            "channel_sequence":    json.dumps([c.value for c in journey.channel_sequence]),
            "steps":               json.dumps([s.model_dump() for s in journey.steps], default=str),
            "current_step_index":  journey.current_step_index,
            "payment_received":    int(journey.payment_received),
            "payment_received_at": journey.payment_received_at.isoformat() if journey.payment_received_at else None,
            "escalated":           int(journey.escalated),
            "escalation_reason":   journey.escalation_reason.value if journey.escalation_reason else None,
            "created_at":          journey.created_at.isoformat(),
            "updated_at":          journey.updated_at.isoformat(),
        })


def update_journey_status(journey_id: str, status: JourneyStatus) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE renewal_journeys SET status = ?, updated_at = ? WHERE journey_id = ?",
            (status.value, datetime.now().isoformat(), journey_id),
        )


def mark_payment_received(journey_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE renewal_journeys
               SET status = 'payment_done', payment_received = 1,
                   payment_received_at = ?, updated_at = ?
               WHERE journey_id = ?""",
            (datetime.now().isoformat(), datetime.now().isoformat(), journey_id),
        )


def get_journey(journey_id: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM renewal_journeys WHERE journey_id = ?", (journey_id,)
        ).fetchone()
    return dict(row) if row else None


# ── Interaction helpers ───────────────────────────────────────────────────────

def log_interaction(interaction: Interaction) -> None:
    sql = """
    INSERT INTO interactions VALUES (
        :interaction_id, :journey_id, :policy_number, :customer_id,
        :channel, :direction, :message_content, :language, :sent_at,
        :outcome, :sentiment_score, :quality_score, :critique_passed,
        :safety_flags, :raw_response
    )
    """
    with get_connection() as conn:
        conn.execute(sql, {
            "interaction_id":  interaction.interaction_id,
            "journey_id":      interaction.journey_id,
            "policy_number":   interaction.policy_number,
            "customer_id":     interaction.customer_id,
            "channel":         interaction.channel.value,
            "direction":       interaction.direction,
            "message_content": interaction.message_content,
            "language":        interaction.language.value,
            "sent_at":         interaction.sent_at.isoformat() if interaction.sent_at else None,
            "outcome":         interaction.outcome.value if interaction.outcome else None,
            "sentiment_score": interaction.sentiment_score,
            "quality_score":   interaction.quality_score,
            "critique_passed": int(interaction.critique_passed) if interaction.critique_passed is not None else None,
            "safety_flags":    json.dumps(interaction.safety_flags),
            "raw_response":    interaction.raw_response,
        })


def get_interactions_for_journey(journey_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM interactions WHERE journey_id = ? ORDER BY sent_at",
            (journey_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Escalation helpers ────────────────────────────────────────────────────────

def create_escalation(case: EscalationCase) -> None:
    sql = """
    INSERT INTO escalation_cases (
        case_id, journey_id, policy_number, customer_id,
        reason, priority, briefing_note, assigned_to,
        resolved, resolved_at, resolution_note, created_at, sla_deadline
    ) VALUES (
        :case_id, :journey_id, :policy_number, :customer_id,
        :reason, :priority, :briefing_note, :assigned_to,
        :resolved, :resolved_at, :resolution_note, :created_at, :sla_deadline
    )
    """
    with get_connection() as conn:
        conn.execute(sql, {
            "case_id":        case.case_id,
            "journey_id":     case.journey_id,
            "policy_number":  case.policy_number,
            "customer_id":    case.customer_id,
            "reason":         case.reason.value,
            "priority":       case.priority.value,
            "briefing_note":  case.briefing_note,
            "assigned_to":    case.assigned_to,
            "resolved":       int(case.resolved),
            "resolved_at":    case.resolved_at.isoformat() if case.resolved_at else None,
            "resolution_note": case.resolution_note,
            "created_at":     case.created_at.isoformat(),
            "sla_deadline":   case.sla_deadline.isoformat() if case.sla_deadline else None,
        })


def get_open_escalations() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM escalation_cases WHERE resolved = 0 ORDER BY priority, created_at",
        ).fetchall()
    return [dict(r) for r in rows]


# ── Stats helpers (for dashboard) ────────────────────────────────────────────

def get_renewal_stats() -> dict:
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM policies WHERE status='active'").fetchone()[0]
        paid  = conn.execute(
            "SELECT COUNT(*) FROM renewal_journeys WHERE payment_received=1"
        ).fetchone()[0]
        escalated = conn.execute(
            "SELECT COUNT(*) FROM escalation_cases WHERE resolved=0"
        ).fetchone()[0]
        in_progress = conn.execute(
            "SELECT COUNT(*) FROM renewal_journeys WHERE status='in_progress'"
        ).fetchone()[0]
    return {
        "total_active_policies": total,
        "payments_received":     paid,
        "open_escalations":      escalated,
        "journeys_in_progress":  in_progress,
        "renewal_rate":          round((paid / total * 100), 1) if total else 0,
    }


# ── Init ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    stats = get_renewal_stats()
    from rich import print as rprint
    rprint("[green]Database ready.[/green]")
    rprint(stats)
