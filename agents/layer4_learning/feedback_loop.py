"""
agents/layer4_learning/feedback_loop.py
─────────────────────────────────────────
Feedback Loop Agent

Closes the learning loop by:
  1. Reading all completed interactions + quality scores from DB
  2. Calculating per-customer "signal strength":
       payment_made / responded → positive signal → lapse score ↓
       opt_out / no_response    → negative signal → lapse score ↑
       objection                → moderate signal → lapse score slight ↑
       safety_flag              → pause signal    → journey paused
  3. Writing feedback_events to DB (audit trail)
  4. Updating lapse_score on renewal_journeys for future run prioritisation
  5. Emitting a FeedbackSummary with aggregate stats
  6. Auto-triggering PropensityAgent.refresh_from_feedback() once enough
     strong-signal events accumulate (threshold = PropensityAgent.REFRESH_THRESHOLD)
     so the next scoring run uses real outcome examples in the prompt.

The feedback loop is designed to run AFTER each dispatch cycle so that
the next run's propensity model starts with updated scores.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from loguru import logger
from rich.console import Console
from rich.table import Table
from rich import box

from core.config import settings


# ── Outcome signals ───────────────────────────────────────────────────────────
# Maps InteractionOutcome value → (lapse_score_delta, signal_label)
OUTCOME_SIGNALS: dict[str, tuple[int, str]] = {
    "payment_made":  (-20, "strong_positive"),
    "responded":     (-8,  "positive"),
    "read":          (-3,  "weak_positive"),
    "delivered":     (-1,  "neutral_positive"),
    "no_response":   (+5,  "weak_negative"),
    "failed":        (+3,  "neutral_negative"),
    "objection":     (+10, "moderate_negative"),
    "opt_out":       (+20, "strong_negative"),
    "escalated":     (+15, "pause_signal"),
    "callback_scheduled": (-5, "positive"),
}

# Quality score adjustments
# If overall quality score < threshold, lapse score gets slight bump (bad comms = worse outcome)
QUALITY_PENALTY_THRESHOLD = 60.0
QUALITY_PENALTY_DELTA     = +3


# ── DB models ─────────────────────────────────────────────────────────────────

@dataclass
class FeedbackEvent:
    event_id:       str
    journey_id:     str
    policy_number:  str
    customer_id:    str
    signal:         str           # e.g. "strong_positive"
    outcome:        str           # raw outcome value
    lapse_delta:    int           # score change applied
    old_score:      float
    new_score:      float
    quality_score:  Optional[float] = None
    created_at:     datetime = field(default_factory=datetime.now)


@dataclass
class FeedbackSummary:
    total_events:               int = 0
    positive_signals:           int = 0
    negative_signals:           int = 0
    avg_lapse_delta:            float = 0.0
    policies_improved:          int = 0   # lapse score went down
    policies_worsened:          int = 0   # lapse score went up
    payments_confirmed:         int = 0
    opt_outs:                   int = 0
    escalations:                int = 0
    propensity_prompt_refreshed: bool = False  # True if prompt was auto-updated


# ── DB helpers ────────────────────────────────────────────────────────────────

def _ensure_feedback_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback_events (
            event_id      TEXT PRIMARY KEY,
            journey_id    TEXT,
            policy_number TEXT,
            customer_id   TEXT,
            signal        TEXT,
            outcome       TEXT,
            lapse_delta   INTEGER,
            old_score     REAL,
            new_score     REAL,
            quality_score REAL,
            created_at    TEXT
        )
    """)
    conn.commit()


def _load_interactions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("""
        SELECT i.interaction_id, i.journey_id, i.policy_number,
               i.customer_id, i.channel, i.outcome,
               j.lapse_score, j.status
        FROM interactions i
        LEFT JOIN renewal_journeys j ON i.journey_id = j.journey_id
        ORDER BY i.sent_at DESC
    """).fetchall()
    return [dict(r) for r in rows]


def _load_quality_scores(conn: sqlite3.Connection) -> dict[str, float]:
    """Returns {journey_id: avg_quality_score}."""
    # Ensure the table exists even if Layer 3 hasn't run yet
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quality_scores (
            score_id      TEXT PRIMARY KEY,
            journey_id    TEXT,
            policy_number TEXT,
            customer_name TEXT,
            channel       TEXT,
            critique_score    REAL,
            compliance_score  REAL,
            safety_score      REAL,
            sentiment_score   REAL,
            total_score       REAL,
            grade             TEXT,
            created_at        TEXT
        )
    """)
    conn.commit()
    rows = conn.execute("""
        SELECT journey_id, AVG(total_score) as avg_score
        FROM quality_scores
        GROUP BY journey_id
    """).fetchall()
    return {r["journey_id"]: r["avg_score"] for r in rows}


def _get_current_lapse(conn: sqlite3.Connection, journey_id: str) -> float:
    row = conn.execute(
        "SELECT lapse_score FROM renewal_journeys WHERE journey_id=?", (journey_id,)
    ).fetchone()
    return float(row["lapse_score"]) if row else 50.0


def _update_lapse_score(conn: sqlite3.Connection, journey_id: str, new_score: float) -> None:
    clamped = max(0.0, min(100.0, new_score))
    conn.execute(
        "UPDATE renewal_journeys SET lapse_score=? WHERE journey_id=?",
        (clamped, journey_id),
    )


def _save_event(conn: sqlite3.Connection, ev: FeedbackEvent) -> None:
    conn.execute("""
        INSERT OR IGNORE INTO feedback_events VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        ev.event_id, ev.journey_id, ev.policy_number, ev.customer_id,
        ev.signal, ev.outcome, ev.lapse_delta,
        ev.old_score, ev.new_score, ev.quality_score,
        ev.created_at.isoformat(),
    ))


# ── Main agent ────────────────────────────────────────────────────────────────

class FeedbackLoopAgent:
    """Reads interaction outcomes + quality scores → updates lapse scores.

    After every run, if enough strong-signal feedback events have accumulated
    (≥ PropensityAgent.REFRESH_THRESHOLD), the PropensityAgent's prompt is
    automatically refreshed with real outcome examples so future scoring runs
    are self-calibrating.
    """

    def __init__(self):
        self._db_path = str(settings.abs_db_path)
        logger.info("FeedbackLoopAgent ready")

    def run(self) -> tuple[list[FeedbackEvent], FeedbackSummary]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        _ensure_feedback_table(conn)

        interactions  = _load_interactions(conn)
        quality_map   = _load_quality_scores(conn)

        events: list[FeedbackEvent] = []
        # Track net delta per journey (aggregate multiple interactions)
        journey_deltas: dict[str, int] = {}

        for iact in interactions:
            journey_id  = iact["journey_id"]
            outcome_val = iact["outcome"] or "no_response"
            delta, signal = OUTCOME_SIGNALS.get(outcome_val, (0, "unknown"))

            # Quality penalty
            q_score = quality_map.get(journey_id)
            if q_score is not None and q_score < QUALITY_PENALTY_THRESHOLD:
                delta += QUALITY_PENALTY_DELTA

            journey_deltas[journey_id] = journey_deltas.get(journey_id, 0) + delta

            old_score = _get_current_lapse(conn, journey_id)
            new_score = max(0.0, min(100.0, old_score + delta))

            ev = FeedbackEvent(
                event_id      = f"FB-{uuid.uuid4().hex[:8].upper()}",
                journey_id    = journey_id,
                policy_number = iact["policy_number"],
                customer_id   = iact["customer_id"],
                signal        = signal,
                outcome       = outcome_val,
                lapse_delta   = delta,
                old_score     = old_score,
                new_score     = new_score,
                quality_score = q_score,
            )
            _save_event(conn, ev)
            events.append(ev)

        # Apply net deltas to journey scores
        for journey_id, net_delta in journey_deltas.items():
            old = _get_current_lapse(conn, journey_id)
            _update_lapse_score(conn, journey_id, old + net_delta)

        conn.commit()
        conn.close()

        # Summary
        pos = sum(1 for e in events if e.lapse_delta < 0)
        neg = sum(1 for e in events if e.lapse_delta > 0)
        summary = FeedbackSummary(
            total_events       = len(events),
            positive_signals   = pos,
            negative_signals   = neg,
            avg_lapse_delta    = sum(e.lapse_delta for e in events) / len(events) if events else 0,
            policies_improved  = sum(1 for e in events if e.new_score < e.old_score),
            policies_worsened  = sum(1 for e in events if e.new_score > e.old_score),
            payments_confirmed = sum(1 for e in events if e.outcome == "payment_made"),
            opt_outs           = sum(1 for e in events if e.outcome == "opt_out"),
            escalations        = sum(1 for e in events if e.outcome == "escalated"),
        )
        logger.info(
            f"Feedback loop complete | {len(events)} events | "
            f"+ve={pos} -ve={neg} | avg_delta={summary.avg_lapse_delta:+.1f}"
        )

        # ── Auto-trigger propensity prompt refresh ───────────────────────────
        # Once enough real outcomes exist the PropensityAgent recalibrates its
        # Gemini prompt with live few-shot examples — no manual intervention needed.
        try:
            from agents.layer1_strategic.propensity import PropensityAgent
            _pa = PropensityAgent.__new__(PropensityAgent)   # no Gemini client needed
            _pa.client = None
            _pa.model  = None
            refreshed = _pa.refresh_from_feedback(
                min_events=PropensityAgent.REFRESH_THRESHOLD
            )
            if refreshed:
                summary.propensity_prompt_refreshed = True
                logger.info(
                    "Propensity prompt auto-refreshed with real outcome examples"
                )
        except Exception as exc:
            logger.warning(f"Propensity auto-refresh skipped: {exc}")

        return events, summary
