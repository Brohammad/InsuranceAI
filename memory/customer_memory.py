"""
memory/customer_memory.py
──────────────────────────
Customer Memory Store

Persists and retrieves per-customer context that agents use to:
  1. Personalise messages (language, tone, channel preference history)
  2. Avoid repeating content already seen/acted upon
  3. Track sentiment trend over time
  4. Build interaction summary for human handoff briefs
  5. Remember objections raised and resolutions offered

Storage: SQLite (same DB as the rest of the system)
         Table: customer_memory (one row per customer, JSON blobs for lists)

Usage:
    mem = CustomerMemoryStore()
    mem.update(customer_id, interaction_dict)
    ctx = mem.get_context(customer_id)  → CustomerContext
    summary = mem.get_summary(customer_id)  → str (for agent prompts)
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from loguru import logger

from core.config import settings


# ═══════════════════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class InteractionSummary:
    interaction_id: str
    channel:        str
    outcome:        str
    sentiment:      float    # -1.0 to +1.0
    objection:      str      # "" if none
    timestamp:      str


@dataclass
class CustomerContext:
    customer_id:          str
    name:                 str
    preferred_language:   str      = "english"
    preferred_channel:    str      = "whatsapp"
    preferred_time:       str      = "18:00-20:00"
    total_interactions:   int      = 0
    last_interaction_at:  str      = ""
    last_channel:         str      = ""
    last_outcome:         str      = ""
    avg_sentiment:        float    = 0.0
    objections_raised:    list[str] = field(default_factory=list)
    channels_tried:       list[str] = field(default_factory=list)
    successful_channel:   str      = ""      # channel that led to positive outcome
    payment_history:      list[str] = field(default_factory=list)
    recent_interactions:  list[InteractionSummary] = field(default_factory=list)
    notes:                str      = ""      # human-editable free text
    updated_at:           str      = ""


# ═══════════════════════════════════════════════════════════════════════════════
#  DB SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS customer_memory (
    customer_id          TEXT PRIMARY KEY,
    name                 TEXT,
    preferred_language   TEXT DEFAULT 'english',
    preferred_channel    TEXT DEFAULT 'whatsapp',
    preferred_time       TEXT DEFAULT '18:00-20:00',
    total_interactions   INTEGER DEFAULT 0,
    last_interaction_at  TEXT,
    last_channel         TEXT,
    last_outcome         TEXT,
    avg_sentiment        REAL DEFAULT 0.0,
    objections_raised    TEXT DEFAULT '[]',   -- JSON list
    channels_tried       TEXT DEFAULT '[]',   -- JSON list
    successful_channel   TEXT DEFAULT '',
    payment_history      TEXT DEFAULT '[]',   -- JSON list
    recent_interactions  TEXT DEFAULT '[]',   -- JSON list (last 10)
    notes                TEXT DEFAULT '',
    updated_at           TEXT
)
"""


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class CustomerMemoryStore:
    """Per-customer persistent memory across all interactions."""

    MAX_RECENT = 10   # keep last N interactions in memory

    def __init__(self):
        self._db_path = str(settings.abs_db_path)
        self._ensure_table()
        logger.info("CustomerMemoryStore ready")

    # ── Table setup ──────────────────────────────────────────────────────────

    def _ensure_table(self) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute(CREATE_TABLE_SQL)
        conn.commit()
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Seed from existing customers ────────────────────────────────────────

    def seed_from_customers(self) -> int:
        """Pre-populate memory rows for all existing customers (idempotent)."""
        conn = self._conn()
        customers = conn.execute(
            "SELECT customer_id, name, preferred_language, preferred_channel, preferred_call_time FROM customers"
        ).fetchall()

        created = 0
        now = datetime.now().isoformat()
        for c in customers:
            existing = conn.execute(
                "SELECT customer_id FROM customer_memory WHERE customer_id=?", (c["customer_id"],)
            ).fetchone()
            if not existing:
                conn.execute("""
                    INSERT INTO customer_memory
                        (customer_id, name, preferred_language, preferred_channel,
                         preferred_time, updated_at)
                    VALUES (?,?,?,?,?,?)
                """, (
                    c["customer_id"], c["name"],
                    c["preferred_language"], c["preferred_channel"],
                    c["preferred_call_time"], now,
                ))
                created += 1

        conn.commit()
        conn.close()
        logger.info(f"CustomerMemoryStore: seeded {created} new records")
        return created

    # ── Update from interaction ──────────────────────────────────────────────

    def update(
        self,
        customer_id:      str,
        channel:          str,
        outcome:          str,
        sentiment:        float = 0.0,
        objection:        str   = "",
        interaction_id:   str   = "",
        message_content:  str   = "",
        payment_received: bool  = False,
    ) -> None:
        """Update memory after an interaction."""
        conn = self._conn()
        now  = datetime.now().isoformat()

        # Load existing
        row = conn.execute(
            "SELECT * FROM customer_memory WHERE customer_id=?", (customer_id,)
        ).fetchone()

        if not row:
            # Auto-create minimal record
            cust = conn.execute(
                "SELECT name, preferred_language, preferred_channel, preferred_call_time FROM customers WHERE customer_id=?",
                (customer_id,)
            ).fetchone()
            name = cust["name"] if cust else customer_id
            conn.execute("""
                INSERT INTO customer_memory (customer_id, name, updated_at)
                VALUES (?,?,?)
            """, (customer_id, name, now))
            conn.commit()
            row = conn.execute(
                "SELECT * FROM customer_memory WHERE customer_id=?", (customer_id,)
            ).fetchone()

        # Parse JSON fields
        objections_raised   = json.loads(row["objections_raised"]   or "[]")
        channels_tried      = json.loads(row["channels_tried"]      or "[]")
        payment_history     = json.loads(row["payment_history"]     or "[]")
        recent_interactions = json.loads(row["recent_interactions"] or "[]")

        # Update fields
        total = (row["total_interactions"] or 0) + 1

        # Rolling sentiment average
        old_sentiment = row["avg_sentiment"] or 0.0
        avg_sentiment = round(
            (old_sentiment * (total - 1) + sentiment) / total, 3
        )

        # Objections
        if objection and objection not in objections_raised:
            objections_raised.append(objection)

        # Channels tried
        if channel not in channels_tried:
            channels_tried.append(channel)

        # Successful channel (positive outcome)
        successful_channel = row["successful_channel"] or ""
        if outcome in ("payment_made", "responded", "read") and not successful_channel:
            successful_channel = channel

        # Payment history
        if payment_received:
            payment_history.append(now[:10])  # date only

        # Recent interactions (keep last N)
        new_entry = {
            "interaction_id": interaction_id,
            "channel":        channel,
            "outcome":        outcome,
            "sentiment":      sentiment,
            "objection":      objection,
            "timestamp":      now,
        }
        recent_interactions.append(new_entry)
        recent_interactions = recent_interactions[-self.MAX_RECENT:]

        # Persist
        conn.execute("""
            UPDATE customer_memory SET
                total_interactions   = ?,
                last_interaction_at  = ?,
                last_channel         = ?,
                last_outcome         = ?,
                avg_sentiment        = ?,
                objections_raised    = ?,
                channels_tried       = ?,
                successful_channel   = ?,
                payment_history      = ?,
                recent_interactions  = ?,
                updated_at           = ?
            WHERE customer_id = ?
        """, (
            total, now, channel, outcome,
            avg_sentiment,
            json.dumps(objections_raised),
            json.dumps(channels_tried),
            successful_channel,
            json.dumps(payment_history),
            json.dumps(recent_interactions),
            now,
            customer_id,
        ))
        conn.commit()
        conn.close()

    # ── Read context ────────────────────────────────────────────────────────

    def get_context(self, customer_id: str) -> Optional[CustomerContext]:
        """Load full context for a customer."""
        conn  = self._conn()
        row   = conn.execute(
            "SELECT * FROM customer_memory WHERE customer_id=?", (customer_id,)
        ).fetchone()
        conn.close()

        if not row:
            return None

        recent_raw = json.loads(row["recent_interactions"] or "[]")
        recent = [
            InteractionSummary(
                interaction_id = r.get("interaction_id", ""),
                channel        = r.get("channel", ""),
                outcome        = r.get("outcome", ""),
                sentiment      = r.get("sentiment", 0.0),
                objection      = r.get("objection", ""),
                timestamp      = r.get("timestamp", ""),
            )
            for r in recent_raw
        ]

        return CustomerContext(
            customer_id         = row["customer_id"],
            name                = row["name"] or "",
            preferred_language  = row["preferred_language"] or "english",
            preferred_channel   = row["preferred_channel"] or "whatsapp",
            preferred_time      = row["preferred_time"] or "18:00-20:00",
            total_interactions  = row["total_interactions"] or 0,
            last_interaction_at = row["last_interaction_at"] or "",
            last_channel        = row["last_channel"] or "",
            last_outcome        = row["last_outcome"] or "",
            avg_sentiment       = row["avg_sentiment"] or 0.0,
            objections_raised   = json.loads(row["objections_raised"] or "[]"),
            channels_tried      = json.loads(row["channels_tried"] or "[]"),
            successful_channel  = row["successful_channel"] or "",
            payment_history     = json.loads(row["payment_history"] or "[]"),
            recent_interactions = recent,
            notes               = row["notes"] or "",
            updated_at          = row["updated_at"] or "",
        )

    # ── Prompt summary ──────────────────────────────────────────────────────

    def get_summary(self, customer_id: str) -> str:
        """
        Return a concise text summary suitable for injecting into agent prompts.
        Format: 3-5 lines of factual context.
        """
        ctx = self.get_context(customer_id)
        if not ctx:
            return "No prior interaction history available for this customer."

        lines = []
        if ctx.total_interactions:
            lines.append(
                f"Prior interactions: {ctx.total_interactions} total. "
                f"Last: {ctx.last_channel} on {ctx.last_interaction_at[:10] if ctx.last_interaction_at else 'unknown'} "
                f"(outcome: {ctx.last_outcome})."
            )
        if ctx.avg_sentiment:
            sentiment_label = "positive" if ctx.avg_sentiment > 0.1 else "negative" if ctx.avg_sentiment < -0.1 else "neutral"
            lines.append(f"Sentiment trend: {sentiment_label} (avg {ctx.avg_sentiment:+.2f}).")
        if ctx.objections_raised:
            lines.append(f"Objections raised previously: {', '.join(ctx.objections_raised[:3])}.")
        if ctx.successful_channel:
            lines.append(f"Most responsive channel: {ctx.successful_channel}.")
        if ctx.channels_tried:
            lines.append(f"Channels already tried: {', '.join(ctx.channels_tried)}.")
        if not ctx.total_interactions:
            lines.append("First contact — no prior interaction history.")

        return " ".join(lines) if lines else "No meaningful history available."

    # ── Bulk load for dashboard ──────────────────────────────────────────────

    def get_all_contexts(self) -> list[CustomerContext]:
        """Load all customer contexts (for dashboard / reporting)."""
        conn  = self._conn()
        rows  = conn.execute("SELECT customer_id FROM customer_memory").fetchall()
        conn.close()
        return [ctx for cid in rows if (ctx := self.get_context(cid["customer_id"]))]

    # ── Stats ────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        conn = self._conn()
        try:
            total  = conn.execute("SELECT COUNT(*) FROM customer_memory").fetchone()[0]
            active = conn.execute(
                "SELECT COUNT(*) FROM customer_memory WHERE total_interactions > 0"
            ).fetchone()[0]
            avg_sent = conn.execute(
                "SELECT AVG(avg_sentiment) FROM customer_memory WHERE total_interactions > 0"
            ).fetchone()[0] or 0.0
        except Exception:
            total = active = 0
            avg_sent = 0.0
        conn.close()
        return {
            "total_customers_tracked": total,
            "with_interactions":       active,
            "avg_sentiment":           round(avg_sent, 3),
        }
