"""
agents/layer4_learning/report_agent.py
────────────────────────────────────────
Report Agent

Generates a structured daily/weekly renewal operations report using
Gemini (gemini-2.0-flash-preview or gemini-2.5-flash in real mode).

Report sections:
  1. Executive Summary      — key numbers in 3 bullets
  2. Renewal Performance    — rate, by segment, by channel
  3. Quality Metrics        — avg score, grade distribution
  4. Safety & Compliance    — flag rates, escalations
  5. A/B Test Winners       — best channel/tone/strategy
  6. Drift Alerts           — any detected anomalies
  7. Top 5 At-Risk Policies — highest remaining lapse scores
  8. Recommendations        — 3-5 actionable next steps

Report saved as Markdown to outputs/reports/report_<timestamp>.md
In mock mode: uses template + DB stats (no LLM call needed).
In real mode: pulls DB stats → feeds Gemini → enriches with insights.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from loguru import logger
from google import genai

from core.config import settings


# ── Output directory ──────────────────────────────────────────────────────────

REPORTS_DIR = Path("outputs/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ── DB data gatherer ──────────────────────────────────────────────────────────

def _gather_stats() -> dict:
    conn = sqlite3.connect(str(settings.abs_db_path))
    conn.row_factory = sqlite3.Row

    # Core renewal stats
    total_policies   = conn.execute("SELECT COUNT(*) FROM policies").fetchone()[0]
    total_journeys   = conn.execute("SELECT COUNT(*) FROM renewal_journeys").fetchone()[0]
    paid             = conn.execute("SELECT COUNT(*) FROM renewal_journeys WHERE status='payment_done'").fetchone()[0]
    in_prog          = conn.execute("SELECT COUNT(*) FROM renewal_journeys WHERE status='in_progress'").fetchone()[0]
    opted_out        = conn.execute("SELECT COUNT(*) FROM renewal_journeys WHERE status='opted_out'").fetchone()[0]
    escalated        = conn.execute("SELECT COUNT(*) FROM renewal_journeys WHERE status='escalated'").fetchone()[0]
    renewal_rate     = round(paid / total_journeys * 100, 1) if total_journeys else 0

    # Premium recovered
    premium_rows = conn.execute("""
        SELECT p.annual_premium FROM renewal_journeys j
        JOIN policies p ON j.policy_number = p.policy_number
        WHERE j.status = 'payment_done'
    """).fetchall()
    premium_recovered = sum(r[0] for r in premium_rows)

    # By segment
    seg_rows = conn.execute("""
        SELECT segment,
               COUNT(*) as total,
               SUM(CASE WHEN status='payment_done' THEN 1 ELSE 0 END) as paid
        FROM renewal_journeys GROUP BY segment
    """).fetchall()
    by_segment = {r[0]: {"total": r[1], "paid": r[2] or 0} for r in seg_rows}

    # By channel
    ch_rows = conn.execute("""
        SELECT channel,
               COUNT(*) as total,
               SUM(CASE WHEN outcome='payment_made' THEN 1 ELSE 0 END) as paid
        FROM interactions GROUP BY channel
    """).fetchall()
    by_channel = {r[0]: {"total": r[1], "paid": r[2] or 0} for r in ch_rows}

    # Total interactions
    total_interactions = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]

    # Quality scores
    try:
        qs_rows = conn.execute("""
            SELECT AVG(total_score), AVG(critique_score),
                   AVG(compliance_score), AVG(safety_score), AVG(sentiment_score),
                   COUNT(*)
            FROM quality_scores
        """).fetchone()
        quality = {
            "avg_total": round(qs_rows[0] or 0, 1),
            "avg_critique": round(qs_rows[1] or 0, 1),
            "avg_compliance": round(qs_rows[2] or 0, 1),
            "avg_safety": round(qs_rows[3] or 0, 1),
            "avg_sentiment": round(qs_rows[4] or 0, 1),
            "total_scored": qs_rows[5] or 0,
        }
        grade_rows = conn.execute("""
            SELECT grade, COUNT(*) FROM quality_scores GROUP BY grade ORDER BY grade
        """).fetchall()
        quality["grades"] = {r[0]: r[1] for r in grade_rows}
    except sqlite3.OperationalError:
        quality = {}

    # Escalations
    try:
        esc_rows = conn.execute("""
            SELECT priority, COUNT(*) FROM escalation_cases GROUP BY priority
        """).fetchall()
        escalations_by_priority = {r[0]: r[1] for r in esc_rows}
        total_escalations = sum(escalations_by_priority.values())
    except sqlite3.OperationalError:
        escalations_by_priority = {}
        total_escalations = 0

    # Feedback stats
    try:
        fb_rows = conn.execute("""
            SELECT AVG(lapse_delta), COUNT(*),
                   SUM(CASE WHEN lapse_delta < 0 THEN 1 ELSE 0 END) as improved
            FROM feedback_events
        """).fetchone()
        feedback = {
            "avg_delta": round(fb_rows[0] or 0, 1),
            "total_events": fb_rows[1] or 0,
            "improved": fb_rows[2] or 0,
        }
    except sqlite3.OperationalError:
        feedback = {}

    # A/B test winners
    try:
        ab_rows = conn.execute("""
            SELECT variant_type, winner, winner_conv_rate, lift_pct, significant
            FROM ab_test_results ORDER BY run_at DESC
        """).fetchall()
        ab_winners = [
            {"type": r[0], "winner": r[1], "rate": r[2], "lift": r[3], "sig": bool(r[4])}
            for r in ab_rows
        ]
    except sqlite3.OperationalError:
        ab_winners = []

    # Drift alerts
    try:
        dr_row = conn.execute("""
            SELECT overall, summary, anomalies FROM drift_reports ORDER BY run_at DESC LIMIT 1
        """).fetchone()
        drift = {"overall": dr_row[0], "summary": dr_row[1]} if dr_row else {"overall": "ok", "summary": "No drift report"}
    except sqlite3.OperationalError:
        drift = {"overall": "ok", "summary": "No drift report yet"}

    # Top at-risk (lapse score > 70, not yet paid)
    at_risk_rows = conn.execute("""
        SELECT j.journey_id, j.policy_number, j.customer_id, j.lapse_score, j.segment
        FROM renewal_journeys j
        WHERE j.status != 'payment_done' AND j.lapse_score > 60
        ORDER BY j.lapse_score DESC LIMIT 5
    """).fetchall()
    at_risk = [dict(r) for r in at_risk_rows]

    conn.close()
    return {
        "generated_at":         datetime.now().isoformat(),
        "total_policies":       total_policies,
        "total_journeys":       total_journeys,
        "paid":                 paid,
        "in_progress":          in_prog,
        "opted_out":            opted_out,
        "escalated_journeys":   escalated,
        "renewal_rate_pct":     renewal_rate,
        "premium_recovered_inr":premium_recovered,
        "total_interactions":   total_interactions,
        "by_segment":           by_segment,
        "by_channel":           by_channel,
        "quality":              quality,
        "total_escalations":    total_escalations,
        "escalations_by_priority": escalations_by_priority,
        "feedback":             feedback,
        "ab_winners":           ab_winners,
        "drift":                drift,
        "at_risk_policies":     at_risk,
    }


# ── Template report (mock / no-LLM path) ─────────────────────────────────────

def _template_report(stats: dict) -> str:
    d = stats
    now = datetime.now().strftime("%d %B %Y %H:%M")
    seg_lines = "\n".join(
        f"  - **{seg}**: {v['paid']}/{v['total']} paid "
        f"({v['paid']/v['total']*100:.0f}%)" if v['total'] else f"  - **{seg}**: 0"
        for seg, v in d.get("by_segment", {}).items()
    )
    ch_lines = "\n".join(
        f"  - **{ch}**: {v['paid']}/{v['total']} conversions "
        f"({v['paid']/v['total']*100:.0f}%)" if v['total'] else f"  - **{ch}**: 0"
        for ch, v in d.get("by_channel", {}).items()
    )
    q = d.get("quality", {})
    grades = q.get("grades", {})
    grade_str = " | ".join(f"{g}:{n}" for g, n in sorted(grades.items()))

    ab_lines = "\n".join(
        f"  - **{r['type'].title()}**: `{r['winner']}` wins "
        f"(conv={r['rate']}%, lift={r['lift']:+.1f}%, "
        f"{'✓ significant' if r['sig'] else '⚠ not significant'})"
        for r in d.get("ab_winners", [])
    ) or "  - No A/B test data yet"

    drift = d.get("drift", {})
    drift_sev = drift.get("overall", "ok").upper()
    drift_icon = {"OK": "✅", "WARNING": "⚠️", "CRITICAL": "🚨"}.get(drift_sev, "ℹ️")

    at_risk_lines = "\n".join(
        f"  {i+1}. `{r['policy_number']}` — score={r['lapse_score']:.0f} | segment={r['segment']}"
        for i, r in enumerate(d.get("at_risk_policies", []))
    ) or "  - No high-risk policies outstanding"

    fb = d.get("feedback", {})
    esc_by_p = d.get("escalations_by_priority", {})
    esc_lines = " | ".join(f"{p}:{n}" for p, n in esc_by_p.items()) or "None"

    return f"""# 📊 RenewAI Daily Operations Report
**Generated:** {now}  
**System:** Suraksha Life Insurance — Project RenewAI

---

## 1. Executive Summary

- 🎯 **Renewal Rate: {d['renewal_rate_pct']}%** — {d['paid']} of {d['total_journeys']} journeys resulted in payment
- 💰 **Premium Recovered: ₹{d['premium_recovered_inr']:,.0f}** across {d['paid']} policies
- ⚠️ **{d['total_escalations']} escalation(s)** require human agent attention

---

## 2. Renewal Performance

| Metric | Value |
|---|---|
| Total Active Policies | {d['total_policies']} |
| Journeys Dispatched | {d['total_journeys']} |
| Payments Received | {d['paid']} |
| In Progress | {d['in_progress']} |
| Opted Out | {d['opted_out']} |
| Escalated | {d['escalated_journeys']} |
| **Renewal Rate** | **{d['renewal_rate_pct']}%** |
| Total Interactions Sent | {d['total_interactions']} |

### By Segment
{seg_lines}

### By Channel
{ch_lines}

---

## 3. Quality Metrics

| Metric | Score |
|---|---|
| Average Quality Score | {q.get('avg_total', 0):.1f}/100 |
| Critique (Message Quality) | {q.get('avg_critique', 0):.1f}/100 |
| Compliance (IRDAI) | {q.get('avg_compliance', 0):.1f}/100 |
| Safety | {q.get('avg_safety', 0):.1f}/100 |
| Sentiment | {q.get('avg_sentiment', 0):.1f}/100 |
| Total Scored | {q.get('total_scored', 0)} |

**Grade Distribution:** {grade_str or 'N/A'}

---

## 4. Safety & Compliance

- **Total Escalations:** {d['total_escalations']} ({esc_lines})
- **Feedback Loop:** {fb.get('total_events', 0)} events | avg lapse delta={fb.get('avg_delta', 0):+.1f} | {fb.get('improved', 0)} policies improved

---

## 5. A/B Test Winners

{ab_lines}

---

## 6. Drift Alerts

{drift_icon} **Status: {drift_sev}**  
{drift.get('summary', 'No drift data.')}

---

## 7. Top At-Risk Policies (unpaid, high lapse score)

{at_risk_lines}

---

## 8. Recommendations

1. **Channel Mix**: Prioritise `{d['ab_winners'][0]['winner'] if d.get('ab_winners') else 'voice'}` channel for high-risk segment based on A/B results.
2. **Compliance**: Add STOP opt-out instructions and policy number to all mock messages before switching to real delivery.
3. **Safety**: Review all `emotional_distress` and `financial_stress` flagged customers — offer payment deferral options.
4. **Re-engagement**: {d['in_progress']} journeys are still in-progress — schedule follow-up touchpoints within 48 hours.
5. **Score Recalibration**: Run propensity model refresh after {fb.get('total_events', 0)} feedback events to update lapse predictions.

---
*Report auto-generated by RenewAI Layer 4 — Report Agent*  
*Model: {settings.model_report} | Mock mode: {settings.mock_delivery}*
"""


# ── Import prompt ─────────────────────────────────────────────────────────────

from prompts.layer4 import ENRICH_PROMPT


# ── Main agent ────────────────────────────────────────────────────────────────

class ReportAgent:
    """Generates daily operations report from DB state."""

    def __init__(self):
        if not settings.mock_delivery:
            self._client = genai.Client(api_key=settings.gemini_api_key)
        logger.info(f"ReportAgent ready | mock={settings.mock_delivery}")

    def generate(self, report_type: str = "daily") -> str:
        """Generate report. Returns Markdown string and saves to outputs/reports/."""
        logger.info(f"Generating {report_type} report...")
        stats = _gather_stats()

        if settings.mock_delivery:
            md = _template_report(stats)
        else:
            # Generate template first, then enrich with LLM
            md = _template_report(stats)
            try:
                prompt = ENRICH_PROMPT.format(
                    stats_json = json.dumps({
                        k: v for k, v in stats.items()
                        if k not in ("at_risk_policies",)
                    }, indent=2)
                )
                response = self._client.models.generate_content(
                    model    = settings.model_report,
                    contents = prompt,
                )
                enriched_summary = response.text.strip()
                # Inject LLM executive summary
                md = md.replace(
                    "## 1. Executive Summary",
                    "## 1. Executive Summary (AI-Generated)\n\n" + enriched_summary + "\n\n---\n\n## 1b. Key Metrics",
                )
            except Exception as e:
                logger.warning(f"LLM enrichment failed ({e}) — using template report")

        # Save to file
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = REPORTS_DIR / f"report_{report_type}_{ts}.md"
        report_path.write_text(md, encoding="utf-8")
        logger.info(f"Report saved → {report_path}")
        return md
