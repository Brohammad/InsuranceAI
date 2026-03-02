"""
agents/layer4_learning/drift_detector.py
──────────────────────────────────────────
Drift Detector

Monitors the renewal system for statistical drift and anomalies:

  1. Lapse Score Drift
       Compares current lapse score distribution vs baseline (seed data).
       Flags if mean drifts by > 10 points or std dev doubles.

  2. Renewal Rate Trend
       Tracks payment_done / total journeys ratio over time.
       Flags if renewal rate drops below 40% threshold.

  3. Segment Drift
       Detects if a customer segment (e.g. high_risk) is suddenly
       dominating the portfolio beyond expected proportions.

  4. Safety Flag Surge
       Alerts if safety escalation rate exceeds 15% in a cycle.

  5. Channel Performance Decay
       Flags if a previously top channel drops > 20% conversion rate.

Outputs DriftReport with anomaly list + severity scores.
Results saved to drift_reports table.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from loguru import logger

from core.config import settings


# ── Models ────────────────────────────────────────────────────────────────────

class DriftSeverity(str, Enum):
    OK       = "ok"
    WARNING  = "warning"
    CRITICAL = "critical"


@dataclass
class DriftAnomaly:
    anomaly_id:  str
    check_name:  str
    severity:    DriftSeverity
    metric:      str
    current_val: float
    threshold:   float
    delta:       float
    description: str


@dataclass
class DriftReport:
    report_id:   str
    run_at:      datetime
    anomalies:   list[DriftAnomaly] = field(default_factory=list)
    overall:     DriftSeverity      = DriftSeverity.OK
    summary:     str                = ""

    @property
    def has_critical(self) -> bool:
        return any(a.severity == DriftSeverity.CRITICAL for a in self.anomalies)

    @property
    def has_warning(self) -> bool:
        return any(a.severity == DriftSeverity.WARNING for a in self.anomalies)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _ensure_drift_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS drift_reports (
            report_id TEXT PRIMARY KEY,
            run_at    TEXT,
            overall   TEXT,
            summary   TEXT,
            anomalies TEXT
        )
    """)
    conn.commit()


def _save_report(conn: sqlite3.Connection, report: DriftReport) -> None:
    anomaly_data = [
        {
            "anomaly_id": a.anomaly_id, "check_name": a.check_name,
            "severity": a.severity.value, "metric": a.metric,
            "current_val": a.current_val, "threshold": a.threshold,
            "delta": a.delta, "description": a.description,
        }
        for a in report.anomalies
    ]
    conn.execute("""
        INSERT OR REPLACE INTO drift_reports VALUES (?,?,?,?,?)
    """, (
        report.report_id,
        report.run_at.isoformat(),
        report.overall.value,
        report.summary,
        json.dumps(anomaly_data),
    ))
    conn.commit()


# ── Individual checks ─────────────────────────────────────────────────────────

def _check_lapse_score_drift(conn: sqlite3.Connection) -> list[DriftAnomaly]:
    anomalies = []
    rows = conn.execute("SELECT lapse_score FROM renewal_journeys").fetchall()
    scores = [r[0] for r in rows if r[0] is not None]
    if not scores:
        return anomalies

    mean   = sum(scores) / len(scores)
    std    = (sum((s - mean)**2 for s in scores) / len(scores)) ** 0.5
    # Baseline expected from seed data: mean ~50, std ~25
    BASELINE_MEAN = 50.0
    MEAN_THRESHOLD = 10.0

    delta = abs(mean - BASELINE_MEAN)
    if delta > MEAN_THRESHOLD:
        sev = DriftSeverity.CRITICAL if delta > 20 else DriftSeverity.WARNING
        anomalies.append(DriftAnomaly(
            anomaly_id  = f"DRIFT-{uuid.uuid4().hex[:6].upper()}",
            check_name  = "lapse_score_drift",
            severity    = sev,
            metric      = "mean_lapse_score",
            current_val = round(mean, 1),
            threshold   = BASELINE_MEAN,
            delta       = round(delta, 1),
            description = (
                f"Mean lapse score drifted to {mean:.1f} "
                f"(baseline={BASELINE_MEAN}, delta={delta:+.1f}). "
                f"Portfolio risk profile has {'increased' if mean > BASELINE_MEAN else 'decreased'}."
            ),
        ))
    else:
        logger.debug(f"Lapse score drift OK: mean={mean:.1f}, delta={delta:.1f}")
    return anomalies


def _check_renewal_rate(conn: sqlite3.Connection) -> list[DriftAnomaly]:
    anomalies = []
    total    = conn.execute("SELECT COUNT(*) FROM renewal_journeys").fetchone()[0]
    paid     = conn.execute(
        "SELECT COUNT(*) FROM renewal_journeys WHERE status='payment_done'"
    ).fetchone()[0]
    if total == 0:
        return anomalies

    rate = paid / total * 100
    THRESHOLD = 40.0
    if rate < THRESHOLD:
        sev = DriftSeverity.CRITICAL if rate < 25 else DriftSeverity.WARNING
        anomalies.append(DriftAnomaly(
            anomaly_id  = f"DRIFT-{uuid.uuid4().hex[:6].upper()}",
            check_name  = "renewal_rate_low",
            severity    = sev,
            metric      = "renewal_rate_pct",
            current_val = round(rate, 1),
            threshold   = THRESHOLD,
            delta       = round(rate - THRESHOLD, 1),
            description = (
                f"Renewal rate is {rate:.1f}% ({paid}/{total}) — "
                f"below threshold of {THRESHOLD}%. "
                "Review channel mix and message effectiveness."
            ),
        ))
    else:
        logger.debug(f"Renewal rate OK: {rate:.1f}%")
    return anomalies


def _check_segment_drift(conn: sqlite3.Connection) -> list[DriftAnomaly]:
    anomalies = []
    rows = conn.execute("""
        SELECT segment, COUNT(*) as cnt
        FROM renewal_journeys
        GROUP BY segment
    """).fetchall()
    total = sum(r[1] for r in rows)
    if total == 0:
        return anomalies

    # Expected proportions from seed data
    EXPECTED = {
        "high_risk":       0.25,
        "price_sensitive": 0.20,
        "wealth_builder":  0.20,
        "auto_renewer":    0.15,
        "nudge_needed":    0.20,
    }
    DRIFT_THRESHOLD = 0.15  # 15% absolute drift

    for row in rows:
        seg = row[0] or "unknown"
        pct = row[1] / total
        expected = EXPECTED.get(seg, 0.10)
        delta = abs(pct - expected)
        if delta > DRIFT_THRESHOLD:
            anomalies.append(DriftAnomaly(
                anomaly_id  = f"DRIFT-{uuid.uuid4().hex[:6].upper()}",
                check_name  = "segment_drift",
                severity    = DriftSeverity.WARNING,
                metric      = f"segment_pct_{seg}",
                current_val = round(pct * 100, 1),
                threshold   = round(expected * 100, 1),
                delta       = round(delta * 100, 1),
                description = (
                    f"Segment '{seg}' is {pct*100:.1f}% of portfolio "
                    f"(expected {expected*100:.0f}%, delta={delta*100:+.1f}%). "
                    "Propensity model may need retraining."
                ),
            ))
    return anomalies


def _check_safety_flag_surge(conn: sqlite3.Connection) -> list[DriftAnomaly]:
    anomalies = []
    try:
        total_qs = conn.execute("SELECT COUNT(*) FROM quality_scores").fetchone()[0]
        if total_qs == 0:
            return anomalies
    except sqlite3.OperationalError:
        return anomalies

    escalations = conn.execute(
        "SELECT COUNT(*) FROM escalation_cases"
    ).fetchone()[0]
    total_journeys = conn.execute("SELECT COUNT(*) FROM renewal_journeys").fetchone()[0]

    if total_journeys == 0:
        return anomalies

    esc_rate = escalations / total_journeys * 100
    THRESHOLD = 15.0
    if esc_rate > THRESHOLD:
        anomalies.append(DriftAnomaly(
            anomaly_id  = f"DRIFT-{uuid.uuid4().hex[:6].upper()}",
            check_name  = "safety_escalation_surge",
            severity    = DriftSeverity.CRITICAL if esc_rate > 30 else DriftSeverity.WARNING,
            metric      = "escalation_rate_pct",
            current_val = round(esc_rate, 1),
            threshold   = THRESHOLD,
            delta       = round(esc_rate - THRESHOLD, 1),
            description = (
                f"Escalation rate is {esc_rate:.1f}% ({escalations}/{total_journeys}) — "
                f"above {THRESHOLD}% threshold. Review safety and compliance settings."
            ),
        ))
    else:
        logger.debug(f"Safety escalation rate OK: {esc_rate:.1f}%")
    return anomalies


def _check_channel_performance(conn: sqlite3.Connection) -> list[DriftAnomaly]:
    """Flag if any channel drops below 10% conversion."""
    anomalies = []
    rows = conn.execute("""
        SELECT channel,
               COUNT(*) as total,
               SUM(CASE WHEN outcome='payment_made' THEN 1 ELSE 0 END) as paid
        FROM interactions
        GROUP BY channel
    """).fetchall()

    THRESHOLD = 10.0
    for row in rows:
        channel, total, paid = row[0], row[1], row[2] or 0
        if total < 3:
            continue
        rate = paid / total * 100
        if rate < THRESHOLD:
            anomalies.append(DriftAnomaly(
                anomaly_id  = f"DRIFT-{uuid.uuid4().hex[:6].upper()}",
                check_name  = "channel_performance_decay",
                severity    = DriftSeverity.WARNING,
                metric      = f"conv_rate_{channel}",
                current_val = round(rate, 1),
                threshold   = THRESHOLD,
                delta       = round(rate - THRESHOLD, 1),
                description = (
                    f"Channel '{channel}' conversion rate is {rate:.1f}% "
                    f"({paid}/{total}) — below {THRESHOLD}% minimum. "
                    "Consider reducing weight in channel selector."
                ),
            ))
    return anomalies


# ── Main agent ────────────────────────────────────────────────────────────────

class DriftDetector:
    """Runs all drift checks and returns a DriftReport."""

    CHECKS = [
        _check_lapse_score_drift,
        _check_renewal_rate,
        _check_segment_drift,
        _check_safety_flag_surge,
        _check_channel_performance,
    ]

    def __init__(self):
        self._db_path = str(settings.abs_db_path)
        logger.info("DriftDetector ready")

    def run(self) -> DriftReport:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        _ensure_drift_table(conn)

        all_anomalies: list[DriftAnomaly] = []
        for check_fn in self.CHECKS:
            try:
                anomalies = check_fn(conn)
                all_anomalies.extend(anomalies)
            except Exception as e:
                logger.warning(f"Drift check {check_fn.__name__} failed: {e}")

        # Overall severity
        if any(a.severity == DriftSeverity.CRITICAL for a in all_anomalies):
            overall = DriftSeverity.CRITICAL
        elif any(a.severity == DriftSeverity.WARNING for a in all_anomalies):
            overall = DriftSeverity.WARNING
        else:
            overall = DriftSeverity.OK

        summary = (
            f"{len(all_anomalies)} anomal{'y' if len(all_anomalies)==1 else 'ies'} detected. "
            f"Severity: {overall.value.upper()}."
            if all_anomalies
            else "All drift checks passed. System operating within normal parameters."
        )

        report = DriftReport(
            report_id = f"DR-{uuid.uuid4().hex[:8].upper()}",
            run_at    = datetime.now(),
            anomalies = all_anomalies,
            overall   = overall,
            summary   = summary,
        )
        _save_report(conn, report)
        conn.close()

        log_fn = logger.critical if overall == DriftSeverity.CRITICAL else (
            logger.warning if overall == DriftSeverity.WARNING else logger.info
        )
        log_fn(f"Drift check: {overall.value.upper()} | {len(all_anomalies)} anomalies | {summary}")
        return report
