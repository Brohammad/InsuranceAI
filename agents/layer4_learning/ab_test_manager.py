"""
agents/layer4_learning/ab_test_manager.py
───────────────────────────────────────────
A/B Test Manager

Tracks which communication variants (channel, tone, strategy) are
performing better on conversion (payment_made) and engagement (responded).

Variants tracked:
  • Channel variants   : whatsapp vs email vs voice vs sms
  • Tone variants      : urgent vs empathetic vs friendly vs informational
  • Strategy variants  : tax_benefit vs family_protection vs lapse_warning vs
                         value_demonstration vs social_proof

For each variant pair the manager computes:
  • Conversion rate    : interactions → payment_made %
  • Engagement rate    : interactions → responded + read %
  • Statistical lift   : (variant_rate - control_rate) / control_rate * 100
  • Sample size        : number of data points
  • Significance flag  : basic chi-square p < 0.05 check

Results written to ab_test_results table in DB.
Winner recommendations emitted for next dispatch cycle.
"""

from __future__ import annotations

import math
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger

from core.config import settings


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class VariantStats:
    variant_type:    str     # "channel" / "tone" / "strategy"
    variant_name:    str     # e.g. "whatsapp"
    total:           int     = 0
    conversions:     int     = 0
    engagements:     int     = 0
    conversion_rate: float   = 0.0
    engagement_rate: float   = 0.0


@dataclass
class ABTestResult:
    test_id:         str
    variant_type:    str
    winner:          str
    runner_up:       str
    winner_conv_rate:float
    runner_up_rate:  float
    lift_pct:        float
    significant:     bool
    sample_size:     int
    all_variants:    list[VariantStats] = field(default_factory=list)
    recommendation:  str = ""
    run_at:          datetime = field(default_factory=datetime.now)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _ensure_ab_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
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
        )
    """)
    conn.commit()


def _load_interactions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("""
        SELECT i.channel, i.outcome,
               j.segment, j.steps
        FROM interactions i
        LEFT JOIN renewal_journeys j ON i.journey_id = j.journey_id
    """).fetchall()
    result = []
    for row in rows:
        steps = []
        try:
            steps = json.loads(row["steps"] or "[]")
        except (json.JSONDecodeError, TypeError):
            pass
        first_step = steps[0] if steps else {}
        result.append({
            "channel":  row["channel"],
            "outcome":  row["outcome"],
            "segment":  row["segment"],
            "tone":     first_step.get("tone", "friendly"),
            "strategy": first_step.get("strategy", "value_demonstration"),
        })
    return result


# ── Statistics ────────────────────────────────────────────────────────────────

def _chi_square_significant(n1: int, c1: int, n2: int, c2: int) -> bool:
    """Simple 2×2 chi-square test. Returns True if p < 0.05."""
    if n1 < 5 or n2 < 5:
        return False
    total   = n1 + n2
    tot_c   = c1 + c2
    tot_nc  = total - tot_c
    if tot_c == 0 or tot_nc == 0:
        return False
    # Expected frequencies
    e11 = n1 * tot_c / total
    e12 = n1 * tot_nc / total
    e21 = n2 * tot_c / total
    e22 = n2 * tot_nc / total
    if 0 in (e11, e12, e21, e22):
        return False
    nc1 = n1 - c1
    nc2 = n2 - c2
    chi2 = (
        (c1  - e11)**2 / e11
        + (nc1 - e12)**2 / e12
        + (c2  - e21)**2 / e21
        + (nc2 - e22)**2 / e22
    )
    # chi2 > 3.84 → p < 0.05 for 1 degree of freedom
    return chi2 > 3.84


_CONVERSION_OUTCOMES = {"payment_made"}
_ENGAGEMENT_OUTCOMES = {"payment_made", "responded", "callback_scheduled"}


def _compute_variants(interactions: list[dict], field_name: str) -> list[VariantStats]:
    stats: dict[str, VariantStats] = {}
    for row in interactions:
        name = (row.get(field_name) or "unknown").lower()
        if name not in stats:
            stats[name] = VariantStats(variant_type=field_name, variant_name=name)
        v = stats[name]
        v.total += 1
        outcome = (row.get("outcome") or "").lower()
        if outcome in _CONVERSION_OUTCOMES:
            v.conversions += 1
        if outcome in _ENGAGEMENT_OUTCOMES:
            v.engagements += 1

    for v in stats.values():
        v.conversion_rate = round(v.conversions / v.total * 100, 1) if v.total else 0.0
        v.engagement_rate = round(v.engagements / v.total * 100, 1) if v.total else 0.0

    return sorted(stats.values(), key=lambda x: x.conversion_rate, reverse=True)


def _build_result(variant_type: str, variants: list[VariantStats]) -> ABTestResult | None:
    if len(variants) < 2:
        return None
    winner     = variants[0]
    runner_up  = variants[1]
    lift       = 0.0
    if runner_up.conversion_rate > 0:
        lift = (winner.conversion_rate - runner_up.conversion_rate) / runner_up.conversion_rate * 100
    sig = _chi_square_significant(
        winner.total, winner.conversions,
        runner_up.total, runner_up.conversions,
    )
    recommendation = (
        f"Use '{winner.variant_name}' as default {variant_type} "
        f"(conv={winner.conversion_rate}% vs {runner_up.variant_name}={runner_up.conversion_rate}%, "
        f"lift={lift:+.1f}%, {'significant ✓' if sig else 'not yet significant — collect more data'})"
    )
    return ABTestResult(
        test_id          = f"AB-{uuid.uuid4().hex[:8].upper()}",
        variant_type     = variant_type,
        winner           = winner.variant_name,
        runner_up        = runner_up.variant_name,
        winner_conv_rate = winner.conversion_rate,
        runner_up_rate   = runner_up.conversion_rate,
        lift_pct         = round(lift, 1),
        significant      = sig,
        sample_size      = sum(v.total for v in variants),
        all_variants     = variants,
        recommendation   = recommendation,
    )


# ── Main agent ────────────────────────────────────────────────────────────────

class ABTestManager:
    """Analyses interaction data to find the best performing variants."""

    def __init__(self):
        self._db_path = str(settings.abs_db_path)
        logger.info("ABTestManager ready")

    def run(self) -> list[ABTestResult]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        _ensure_ab_table(conn)

        interactions = _load_interactions(conn)
        logger.info(f"A/B test analysis over {len(interactions)} interactions")

        results: list[ABTestResult] = []

        for field_name in ("channel", "tone", "strategy"):
            variants = _compute_variants(interactions, field_name)
            result   = _build_result(field_name, variants)
            if result:
                # Save to DB
                conn.execute("""
                    INSERT OR REPLACE INTO ab_test_results VALUES
                    (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    result.test_id, result.variant_type,
                    result.winner, result.runner_up,
                    result.winner_conv_rate, result.runner_up_rate,
                    result.lift_pct, int(result.significant),
                    result.sample_size, result.recommendation,
                    result.run_at.isoformat(),
                ))
                results.append(result)
                logger.info(
                    f"A/B {field_name}: winner='{result.winner}' "
                    f"conv={result.winner_conv_rate}% lift={result.lift_pct:+.1f}% "
                    f"sig={result.significant}"
                )

        conn.commit()
        conn.close()
        return results
