"""
agents/layer3_quality/quality_scoring.py
──────────────────────────────────────────
Quality Scoring Agent

Aggregates all Layer 3 quality signals for a single interaction into
one composite Quality Score (0–100) and a letter grade (A/B/C/D/F).

Inputs (all optional, scored 0 if not provided):
  • CritiqueResult   → weights 35%  (message quality)
  • ComplianceResult → weights 25%  (IRDAI compliance)
  • SafetyResult     → weights 20%  (no flags = full marks)
  • SentimentResult  → weights 20%  (customer responded positively)

Output: QualityScore dataclass with breakdown + recommendations.

Also provides batch_score() to score all interactions from DB and
write results to a quality_scores table.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from loguru import logger

from core.config import settings
from agents.layer3_quality.critique_agent   import CritiqueResult
from agents.layer3_quality.compliance_agent import ComplianceResult
from agents.layer3_quality.safety_agent     import SafetyResult, SafetyFlag
from agents.layer3_quality.sentiment_agent  import SentimentResult, SentimentPolarity, CustomerIntent


# ── Score model ───────────────────────────────────────────────────────────────

@dataclass
class QualityScore:
    score_id:          str
    journey_id:        str
    policy_number:     str
    customer_name:     str
    channel:           str

    # Component scores (0–100 each)
    critique_score:    float = 0.0
    compliance_score:  float = 0.0
    safety_score:      float = 0.0
    sentiment_score:   float = 0.0

    # Composite
    total_score:       float = 0.0
    grade:             str   = "F"
    scored_at:         datetime = field(default_factory=datetime.now)

    # Explanations
    strengths:         list[str] = field(default_factory=list)
    improvements:      list[str] = field(default_factory=list)
    summary:           str = ""


# ── Grade thresholds ──────────────────────────────────────────────────────────

def _grade(score: float) -> str:
    if score >= 90: return "A"
    if score >= 80: return "B"
    if score >= 65: return "C"
    if score >= 50: return "D"
    return "F"


# ── Scoring logic ─────────────────────────────────────────────────────────────

def _score_critique(c: Optional[CritiqueResult]) -> tuple[float, list[str], list[str]]:
    if c is None:
        return 50.0, ["No critique available (neutral score applied)"], []
    raw = (
        c.tone_score * 0.30
        + c.accuracy_score * 0.25
        + c.personalisation_score * 0.25
        + c.conversion_likelihood * 0.20
    ) * 10  # scale 1–10 → 10–100
    strengths = []
    improvements = []
    if c.tone_score >= 8:         strengths.append(f"Excellent tone ({c.tone_score}/10)")
    if c.accuracy_score >= 8:     strengths.append(f"High accuracy ({c.accuracy_score}/10)")
    if c.personalisation_score < 6: improvements.append("Improve personalisation depth")
    if not c.approved:            improvements.append("Message needs rewrite before sending")
    if c.issues:                  improvements.extend(c.issues[:2])
    return round(min(raw, 100.0), 1), strengths, improvements


def _score_compliance(c: Optional[ComplianceResult]) -> tuple[float, list[str], list[str]]:
    if c is None:
        return 50.0, [], ["No compliance check — assume partial compliance"]
    if c.rules_checked == 0:
        return 100.0, ["No rules applicable"], []
    pct = (c.rules_checked - c.rules_failed) / c.rules_checked * 100
    strengths    = [f"Passed {c.rules_checked - c.rules_failed}/{c.rules_checked} IRDAI rules"]
    improvements = [f"Fix: {r.rule_name} — {r.note}" for r in c.failed_rules if r.note]
    return round(pct, 1), strengths, improvements


def _score_safety(s: Optional[SafetyResult]) -> tuple[float, list[str], list[str]]:
    if s is None:
        return 100.0, ["No safety flags"], []
    # Any non-CLEAR flag zeroes the safety component entirely
    if s.flag != SafetyFlag.CLEAR:
        improvements = [f"Safety flag '{s.flag.value}' detected — {s.agent_note}"] if s.agent_note else [f"Safety flag '{s.flag.value}' detected"]
        return 0.0, [], improvements
    return 100.0, ["No safety concerns"], []


def _score_sentiment(s: Optional[SentimentResult]) -> tuple[float, list[str], list[str]]:
    if s is None:
        return 50.0, [], ["No sentiment data available"]
    # Map score (-1 to +1) → 0–100
    raw = (s.score + 1.0) / 2.0 * 100
    strengths    = [f"Positive customer response (score={s.score:+.2f})"] if s.score > 0.3 else []
    improvements = [f"Customer is {s.polarity.value} — adjust follow-up strategy"] if s.score < 0 else []
    return round(raw, 1), strengths, improvements


# ── Main agent class ──────────────────────────────────────────────────────────

class QualityScoringAgent:
    """Aggregates Layer 3 signals into a composite quality score."""

    WEIGHTS = {
        "critique":   0.35,
        "compliance": 0.25,
        "safety":     0.20,
        "sentiment":  0.20,
    }

    def __init__(self):
        logger.info("QualityScoringAgent ready")

    def score(
        self,
        journey_id:    str,
        policy_number: str,
        customer_name: str,
        channel:       str,
        critique:   Optional[CritiqueResult]   = None,
        compliance: Optional[ComplianceResult] = None,
        safety:     Optional[SafetyResult]     = None,
        sentiment:  Optional[SentimentResult]  = None,
    ) -> QualityScore:
        """Calculate composite quality score for one interaction."""

        c_score, c_str, c_imp = _score_critique(critique)
        co_score, co_str, co_imp = _score_compliance(compliance)
        sa_score, sa_str, sa_imp = _score_safety(safety)
        se_score, se_str, se_imp = _score_sentiment(sentiment)

        total = (
            c_score  * self.WEIGHTS["critique"]
            + co_score * self.WEIGHTS["compliance"]
            + sa_score * self.WEIGHTS["safety"]
            + se_score * self.WEIGHTS["sentiment"]
        )
        total = round(total, 1)
        grade = _grade(total)

        all_strengths    = c_str + co_str + sa_str + se_str
        all_improvements = c_imp + co_imp + sa_imp + se_imp

        summary = (
            f"Grade {grade} ({total}/100) | "
            f"Critique:{c_score:.0f} Compliance:{co_score:.0f} "
            f"Safety:{sa_score:.0f} Sentiment:{se_score:.0f}"
        )

        result = QualityScore(
            score_id       = f"QS-{uuid.uuid4().hex[:8].upper()}",
            journey_id     = journey_id,
            policy_number  = policy_number,
            customer_name  = customer_name,
            channel        = channel,
            critique_score = c_score,
            compliance_score=co_score,
            safety_score   = sa_score,
            sentiment_score= se_score,
            total_score    = total,
            grade          = grade,
            strengths      = all_strengths[:4],
            improvements   = all_improvements[:4],
            summary        = summary,
        )
        logger.info(f"QualityScore → {customer_name} | {channel} | {grade} ({total}/100)")
        return result

    def save_score(self, qs: QualityScore) -> None:
        """Persist quality score to DB."""
        conn = sqlite3.connect(str(settings.abs_db_path))
        conn.execute("""
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
            )
        """)
        import json
        conn.execute("""
            INSERT OR REPLACE INTO quality_scores VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            qs.score_id, qs.journey_id, qs.policy_number, qs.customer_name,
            qs.channel, qs.critique_score, qs.compliance_score,
            qs.safety_score, qs.sentiment_score, qs.total_score, qs.grade,
            qs.summary,
            json.dumps(qs.strengths),
            json.dumps(qs.improvements),
            qs.scored_at.isoformat(),
        ))
        conn.commit()
        conn.close()
        logger.debug(f"Quality score {qs.score_id} saved to DB")


# ── Backward-compat function alias ───────────────────────────────────────────
# Tests import: from agents.layer3_quality.quality_scoring import compute_quality_score
# The old API accepted old-style dataclasses with different field names.
# We translate them here before delegating to QualityScoringAgent.score().

def compute_quality_score(
    journey_id:    str,
    policy_number: str,
    customer_name: str,
    channel:       str,
    critique:   Optional[CritiqueResult]   = None,
    compliance: Optional[ComplianceResult] = None,
    safety:     Optional[SafetyResult]     = None,
    sentiment:  Optional[SentimentResult]  = None,
) -> "QualityScore":
    """
    Backward-compatible wrapper around QualityScoringAgent.score().

    The test suite passes old-style dataclasses that use different field names
    (e.g. SafetyResult(is_safe=True, flags=[]) or
          ComplianceResult(rules_passed=3, violations=[])).
    This function translates those to the current dataclass shapes before scoring.
    """
    # ── Translate SafetyResult (old: is_safe/distress_detected/flags/severity) ──
    # No translation needed — SafetyResult.__post_init__ syncs is_safe ↔ flag

    # ── Translate ComplianceResult (old: rules_passed/violations/call_window_ok) ──
    # No translation needed — ComplianceResult.__post_init__ syncs the fields

    # ── Translate SentimentResult (old: magnitude/customer_intent) ──
    # No translation needed — SentimentResult.__post_init__ handles customer_intent mapping

    return QualityScoringAgent().score(
        journey_id    = journey_id,
        policy_number = policy_number,
        customer_name = customer_name,
        channel       = channel,
        critique      = critique,
        compliance    = compliance,
        safety        = safety,
        sentiment     = sentiment,
    )
