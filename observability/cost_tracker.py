"""
observability/cost_tracker.py
──────────────────────────────
Token + API call cost tracker for Project RenewAI.

Responsibilities:
  1. Track every Gemini API call: model, tokens (in/out), cost
  2. Track every external API call: ElevenLabs, Razorpay, Twilio
  3. Persist to cost_events table in SQLite DB
  4. Roll-up summaries: per-journey, per-agent, per-day, per-model
  5. Budget alerts: warn when daily spend crosses threshold

Cost reference (approximate, subject to Gemini pricing changes):
  gemini-2.5-flash       : $0.00015 / 1K input, $0.00060 / 1K output
  gemini-2.5-pro         : $0.00125 / 1K input, $0.00500 / 1K output
  gemini-3-flash-preview : $0.00015 / 1K input, $0.00060 / 1K output
  gemini-3.1-pro-preview : $0.00125 / 1K input, $0.00500 / 1K output
  ElevenLabs TTS         : $0.00030 / 1K characters
  Twilio WhatsApp        : $0.00500 / message (India)
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional

from loguru import logger

from core.config import settings


# ── Pricing table (USD per unit) ──────────────────────────────────────────────

GEMINI_PRICE: dict[str, dict[str, float]] = {
    "gemini-2.5-flash":        {"input_per_1k": 0.00015, "output_per_1k": 0.00060},
    "gemini-2.5-pro":          {"input_per_1k": 0.00125, "output_per_1k": 0.00500},
    "gemini-3-flash-preview":  {"input_per_1k": 0.00015, "output_per_1k": 0.00060},
    "gemini-3.1-pro-preview":  {"input_per_1k": 0.00125, "output_per_1k": 0.00500},
}

ELEVENLABS_PRICE_PER_1K_CHARS: float = 0.00030
TWILIO_PRICE_PER_MESSAGE: float      = 0.00500
RAZORPAY_PRICE_PER_TXN: float        = 0.00200   # $0.002 per payment link created

USD_TO_INR: float = 84.0   # approximate, not real-time

# Daily budget threshold (INR) — alert above this
DAILY_BUDGET_INR: float = 500.0


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class CostEvent:
    event_id:     str
    journey_id:   Optional[str]
    agent_name:   str           # e.g. "orchestrator", "whatsapp_agent"
    api:          str           # "gemini", "elevenlabs", "twilio", "razorpay"
    model:        Optional[str]
    input_tokens: int
    output_tokens:int
    cost_usd:     float
    cost_inr:     float
    metadata:     str           # JSON blob
    recorded_at:  str


@dataclass
class DailySummary:
    day:            str
    total_calls:    int
    total_tokens:   int
    total_cost_usd: float
    total_cost_inr: float
    over_budget:    bool


@dataclass
class JourneyCostSummary:
    journey_id:     str
    total_calls:    int
    total_tokens:   int
    total_cost_inr: float
    breakdown:      dict[str, float]   # api → cost_inr


# ── DB setup ──────────────────────────────────────────────────────────────────

def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cost_events (
            event_id      TEXT PRIMARY KEY,
            journey_id    TEXT,
            agent_name    TEXT,
            api           TEXT,
            model         TEXT,
            input_tokens  INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cost_usd      REAL DEFAULT 0,
            cost_inr      REAL DEFAULT 0,
            metadata      TEXT DEFAULT '{}',
            recorded_at   TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cost_journey
        ON cost_events(journey_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cost_day
        ON cost_events(DATE(recorded_at))
    """)
    conn.commit()


# ── Cost calculation helpers ──────────────────────────────────────────────────

def calc_gemini_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Return cost in USD for a Gemini API call."""
    prices = GEMINI_PRICE.get(model, GEMINI_PRICE["gemini-2.5-flash"])
    cost = (input_tokens  / 1000 * prices["input_per_1k"]
          + output_tokens / 1000 * prices["output_per_1k"])
    return round(cost, 8)


def calc_elevenlabs_cost(char_count: int) -> float:
    return round(char_count / 1000 * ELEVENLABS_PRICE_PER_1K_CHARS, 8)


def calc_twilio_cost(message_count: int = 1) -> float:
    return round(message_count * TWILIO_PRICE_PER_MESSAGE, 8)


def calc_razorpay_cost(txn_count: int = 1) -> float:
    return round(txn_count * RAZORPAY_PRICE_PER_TXN, 8)


# ── Main tracker ──────────────────────────────────────────────────────────────

class CostTracker:
    """
    Thread-safe cost tracker.

    Usage:
        tracker = CostTracker()
        tracker.record_gemini(
            journey_id="JRN-001",
            agent_name="orchestrator",
            model="gemini-3.1-pro-preview",
            input_tokens=1200,
            output_tokens=350,
        )
    """

    def __init__(self):
        self._db = str(settings.abs_db_path)
        with sqlite3.connect(self._db) as conn:
            _ensure_table(conn)
        logger.info("CostTracker ready")

    # ── Record methods ────────────────────────────────────────────────────────

    def record_gemini(
        self,
        agent_name:    str,
        model:         str,
        input_tokens:  int,
        output_tokens: int,
        journey_id:    Optional[str] = None,
        metadata:      str = "{}",
    ) -> CostEvent:
        cost_usd = calc_gemini_cost(model, input_tokens, output_tokens)
        return self._record(
            journey_id    = journey_id,
            agent_name    = agent_name,
            api           = "gemini",
            model         = model,
            input_tokens  = input_tokens,
            output_tokens = output_tokens,
            cost_usd      = cost_usd,
            metadata      = metadata,
        )

    def record_elevenlabs(
        self,
        agent_name: str,
        char_count: int,
        journey_id: Optional[str] = None,
        metadata:   str = "{}",
    ) -> CostEvent:
        cost_usd = calc_elevenlabs_cost(char_count)
        return self._record(
            journey_id    = journey_id,
            agent_name    = agent_name,
            api           = "elevenlabs",
            model         = "eleven_multilingual_v2",
            input_tokens  = char_count,
            output_tokens = 0,
            cost_usd      = cost_usd,
            metadata      = metadata,
        )

    def record_twilio(
        self,
        agent_name:     str,
        message_count:  int = 1,
        journey_id:     Optional[str] = None,
        metadata:       str = "{}",
    ) -> CostEvent:
        cost_usd = calc_twilio_cost(message_count)
        return self._record(
            journey_id    = journey_id,
            agent_name    = agent_name,
            api           = "twilio",
            model         = None,
            input_tokens  = message_count,
            output_tokens = 0,
            cost_usd      = cost_usd,
            metadata      = metadata,
        )

    def record_razorpay(
        self,
        agent_name: str,
        journey_id: Optional[str] = None,
        metadata:   str = "{}",
    ) -> CostEvent:
        cost_usd = calc_razorpay_cost(1)
        return self._record(
            journey_id    = journey_id,
            agent_name    = agent_name,
            api           = "razorpay",
            model         = None,
            input_tokens  = 1,
            output_tokens = 0,
            cost_usd      = cost_usd,
            metadata      = metadata,
        )

    # ── Query methods ─────────────────────────────────────────────────────────

    def daily_summary(self, day: Optional[str] = None) -> DailySummary:
        """Cost summary for a calendar day (YYYY-MM-DD, default today)."""
        day = day or date.today().isoformat()
        with sqlite3.connect(self._db) as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*)                          AS calls,
                    COALESCE(SUM(input_tokens),0)
                        + COALESCE(SUM(output_tokens),0) AS tokens,
                    COALESCE(SUM(cost_usd),0)         AS cost_usd,
                    COALESCE(SUM(cost_inr),0)         AS cost_inr
                FROM cost_events
                WHERE DATE(recorded_at) = ?
            """, (day,)).fetchone()
        calls, tokens, cost_usd, cost_inr = row
        return DailySummary(
            day            = day,
            total_calls    = calls,
            total_tokens   = tokens,
            total_cost_usd = round(cost_usd, 6),
            total_cost_inr = round(cost_inr, 4),
            over_budget    = cost_inr > DAILY_BUDGET_INR,
        )

    def journey_summary(self, journey_id: str) -> JourneyCostSummary:
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute("""
                SELECT api,
                       COUNT(*)               AS calls,
                       SUM(input_tokens + output_tokens) AS tokens,
                       SUM(cost_inr)          AS cost_inr
                FROM cost_events
                WHERE journey_id = ?
                GROUP BY api
            """, (journey_id,)).fetchall()
        total_calls = sum(r[1] for r in rows)
        total_tokens = sum(r[2] for r in rows)
        total_inr   = sum(r[3] for r in rows)
        breakdown   = {r[0]: round(r[3], 4) for r in rows}
        return JourneyCostSummary(
            journey_id     = journey_id,
            total_calls    = total_calls,
            total_tokens   = total_tokens,
            total_cost_inr = round(total_inr, 4),
            breakdown      = breakdown,
        )

    def top_agents(self, day: Optional[str] = None, limit: int = 10) -> list[dict]:
        """Return top N most expensive agents for a day."""
        day = day or date.today().isoformat()
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute(f"""
                SELECT agent_name,
                       COUNT(*)          AS calls,
                       SUM(cost_inr)     AS total_inr
                FROM cost_events
                WHERE DATE(recorded_at) = ?
                GROUP BY agent_name
                ORDER BY total_inr DESC
                LIMIT {limit}
            """, (day,)).fetchall()
        return [{"agent": r[0], "calls": r[1], "cost_inr": round(r[2], 4)} for r in rows]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _record(
        self,
        agent_name:    str,
        api:           str,
        cost_usd:      float,
        input_tokens:  int   = 0,
        output_tokens: int   = 0,
        model:         Optional[str] = None,
        journey_id:    Optional[str] = None,
        metadata:      str   = "{}",
    ) -> CostEvent:
        event = CostEvent(
            event_id      = str(uuid.uuid4()),
            journey_id    = journey_id,
            agent_name    = agent_name,
            api           = api,
            model         = model,
            input_tokens  = input_tokens,
            output_tokens = output_tokens,
            cost_usd      = cost_usd,
            cost_inr      = round(cost_usd * USD_TO_INR, 6),
            metadata      = metadata,
            recorded_at   = datetime.now().isoformat(),
        )

        with sqlite3.connect(self._db) as conn:
            _ensure_table(conn)
            conn.execute("""
                INSERT INTO cost_events VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                event.event_id, event.journey_id, event.agent_name,
                event.api, event.model, event.input_tokens, event.output_tokens,
                event.cost_usd, event.cost_inr, event.metadata, event.recorded_at,
            ))

        if event.cost_inr > 10:
            logger.warning(
                f"High cost event: {agent_name}/{api} = ₹{event.cost_inr:.4f}"
            )
        else:
            logger.debug(
                f"Cost: {agent_name}/{api} = ₹{event.cost_inr:.4f} "
                f"({input_tokens}in/{output_tokens}out tokens)"
            )

        # Daily budget alert
        summary = self.daily_summary()
        if summary.over_budget:
            logger.warning(
                f"⚠️  Daily budget exceeded: ₹{summary.total_cost_inr:.2f} > "
                f"₹{DAILY_BUDGET_INR:.0f} limit"
            )

        return event
