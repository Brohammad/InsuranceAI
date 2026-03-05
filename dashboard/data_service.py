"""
dashboard/data_service.py
─────────────────────────
Thin read-only data layer shared by all Streamlit pages.
All queries return plain dicts / DataFrames — no ORM.
Defensive: every function returns empty data on any DB error so the
dashboard never hard-crashes due to a missing/stale table.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# ── Resolve DB path ────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = str(_ROOT / "data" / "renewai.db")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate() -> None:
    """
    Idempotent schema migrations — run at import time.
    Adds columns/tables that were introduced after the initial deploy.
    Uses CREATE TABLE IF NOT EXISTS and ALTER TABLE ... ADD COLUMN (safe to re-run).
    """
    try:
        with _conn() as conn:
            # --- quality_scores ---
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
            # --- ab_test_results ---
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

            # --- escalation_cases: add agent_name if missing ---
            esc_cols = {r[1] for r in conn.execute("PRAGMA table_info(escalation_cases)").fetchall()}
            if esc_cols and "agent_name" not in esc_cols:
                conn.execute("ALTER TABLE escalation_cases ADD COLUMN agent_name TEXT")
                conn.commit()
    except Exception:
        pass  # DB doesn't exist yet — _ensure_db() in app.py handles creation


_migrate()


# ── Overview KPIs ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=5)
def get_overview_kpis() -> dict[str, Any]:
    """Return headline numbers for the Overview page."""
    defaults: dict[str, Any] = {
        "total_customers": 0, "total_policies": 0, "due_30_days": 0,
        "renewed": 0, "total_journeys": 0, "conversion_rate": 0.0,
        "escalated_open": 0, "premium_collected": 0, "avg_quality_score": 0.0,
    }
    try:
        with _conn() as conn:
            total_customers = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
            total_policies  = conn.execute("SELECT COUNT(*) FROM policies").fetchone()[0]
            due_30          = conn.execute("""
                SELECT COUNT(*) FROM policies
                WHERE renewal_due_date BETWEEN date('now') AND date('now','+30 days')
                AND status != 'lapsed'
            """).fetchone()[0]
            renewed         = conn.execute(
                "SELECT COUNT(*) FROM renewal_journeys WHERE payment_received = 1"
            ).fetchone()[0]
            total_journeys  = conn.execute("SELECT COUNT(*) FROM renewal_journeys").fetchone()[0]
            escalated_open  = conn.execute(
                "SELECT COUNT(*) FROM escalation_cases WHERE resolved = 0"
            ).fetchone()[0]
            total_premium   = conn.execute("""
                SELECT COALESCE(SUM(p.annual_premium),0)
                FROM policies p
                JOIN renewal_journeys rj ON rj.policy_number = p.policy_number
                WHERE rj.payment_received = 1
            """).fetchone()[0]
            avg_quality     = conn.execute(
                "SELECT COALESCE(AVG(total_score),0) FROM quality_scores"
            ).fetchone()[0]
        conversion_rate = round(renewed / total_journeys * 100, 1) if total_journeys else 0.0
        return {
            "total_customers":   total_customers,
            "total_policies":    total_policies,
            "due_30_days":       due_30,
            "renewed":           renewed,
            "total_journeys":    total_journeys,
            "conversion_rate":   conversion_rate,
            "escalated_open":    escalated_open,
            "premium_collected": total_premium,
            "avg_quality_score": round(avg_quality, 1),
        }
    except Exception:
        return defaults


# ── Journey funnel ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=5)
def get_journey_funnel() -> pd.DataFrame:
    try:
        with _conn() as conn:
            rows = conn.execute("""
                SELECT status, COUNT(*) AS count
                FROM renewal_journeys GROUP BY status
            """).fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=5)
def get_recent_journeys(limit: int = 50) -> pd.DataFrame:
    try:
        with _conn() as conn:
            rows = conn.execute(f"""
                SELECT rj.journey_id, rj.policy_number, c.name AS customer_name,
                       rj.status, rj.segment, rj.lapse_score,
                       rj.payment_received, rj.escalated,
                       rj.created_at, rj.updated_at
                FROM renewal_journeys rj
                LEFT JOIN customers c ON c.customer_id = rj.customer_id
                ORDER BY rj.updated_at DESC LIMIT {limit}
            """).fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception:
        return pd.DataFrame()


# ── Channel breakdown ──────────────────────────────────────────────────────────

@st.cache_data(ttl=5)
def get_channel_stats() -> pd.DataFrame:
    try:
        with _conn() as conn:
            rows = conn.execute("""
                SELECT channel,
                       COUNT(*) AS total_interactions,
                       ROUND(AVG(quality_score),2)  AS avg_quality,
                       ROUND(AVG(sentiment_score),2) AS avg_sentiment
                FROM interactions GROUP BY channel
            """).fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=5)
def get_interaction_timeline() -> pd.DataFrame:
    try:
        with _conn() as conn:
            rows = conn.execute("""
                SELECT DATE(sent_at) AS day, channel, COUNT(*) AS count
                FROM interactions
                GROUP BY day, channel ORDER BY day
            """).fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception:
        return pd.DataFrame()


# ── Quality scores ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=5)
def get_quality_distribution() -> pd.DataFrame:
    try:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT grade, COUNT(*) AS count FROM quality_scores GROUP BY grade"
            ).fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=5)
def get_quality_trend() -> pd.DataFrame:
    try:
        with _conn() as conn:
            rows = conn.execute("""
                SELECT DATE(scored_at) AS day,
                       ROUND(AVG(total_score),2) AS avg_score
                FROM quality_scores GROUP BY day ORDER BY day
            """).fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=5)
def get_recent_quality_scores(limit: int = 30) -> pd.DataFrame:
    try:
        with _conn() as conn:
            rows = conn.execute(f"""
                SELECT policy_number, customer_name, channel, grade,
                       total_score, critique_score, compliance_score,
                       safety_score, sentiment_score, summary, scored_at
                FROM quality_scores ORDER BY scored_at DESC LIMIT {limit}
            """).fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception:
        return pd.DataFrame()


# ── Customer table ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=5)
def get_customers(search: str = "") -> pd.DataFrame:
    try:
        with _conn() as conn:
            if search:
                rows = conn.execute("""
                    SELECT c.customer_id, c.name, c.age, c.city, c.state,
                           c.preferred_language, c.preferred_channel,
                           c.email, c.phone, c.is_on_dnd,
                           COUNT(p.policy_number) AS policies
                    FROM customers c
                    LEFT JOIN policies p ON p.customer_id = c.customer_id
                    WHERE c.name LIKE ? OR c.phone LIKE ? OR c.email LIKE ?
                    GROUP BY c.customer_id ORDER BY c.name
                """, (f"%{search}%", f"%{search}%", f"%{search}%")).fetchall()
            else:
                rows = conn.execute("""
                    SELECT c.customer_id, c.name, c.age, c.city, c.state,
                           c.preferred_language, c.preferred_channel,
                           c.email, c.phone, c.is_on_dnd,
                           COUNT(p.policy_number) AS policies
                    FROM customers c
                    LEFT JOIN policies p ON p.customer_id = c.customer_id
                    GROUP BY c.customer_id ORDER BY c.name
                """).fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=5)
def get_customer_detail(customer_id: str) -> dict[str, Any]:
    try:
        with _conn() as conn:
            cust         = conn.execute("SELECT * FROM customers WHERE customer_id=?", (customer_id,)).fetchone()
            policies     = conn.execute("SELECT * FROM policies WHERE customer_id=?", (customer_id,)).fetchall()
            journeys     = conn.execute(
                "SELECT * FROM renewal_journeys WHERE customer_id=? ORDER BY created_at DESC", (customer_id,)
            ).fetchall()
            interactions = conn.execute(
                "SELECT * FROM interactions WHERE customer_id=? ORDER BY sent_at DESC LIMIT 20", (customer_id,)
            ).fetchall()
        return {
            "customer":     dict(cust) if cust else {},
            "policies":     [dict(p) for p in policies],
            "journeys":     [dict(j) for j in journeys],
            "interactions": [dict(i) for i in interactions],
        }
    except Exception:
        return {"customer": {}, "policies": [], "journeys": [], "interactions": []}


# ── Segment breakdown ──────────────────────────────────────────────────────────

@st.cache_data(ttl=5)
def get_segment_breakdown() -> pd.DataFrame:
    try:
        with _conn() as conn:
            rows = conn.execute("""
                SELECT segment,
                       COUNT(*) AS journeys,
                       SUM(payment_received) AS renewed,
                       ROUND(AVG(lapse_score),3) AS avg_lapse_score
                FROM renewal_journeys GROUP BY segment
            """).fetchall()
        df = pd.DataFrame([dict(r) for r in rows])
        if not df.empty:
            df["conversion_pct"] = (df["renewed"] / df["journeys"] * 100).round(1)
        return df
    except Exception:
        return pd.DataFrame()


# ── Escalation queue ───────────────────────────────────────────────────────────

@st.cache_data(ttl=5)
def get_open_escalations() -> pd.DataFrame:
    try:
        with _conn() as conn:
            cols      = {r[1] for r in conn.execute("PRAGMA table_info(escalation_cases)").fetchall()}
            agent_col = "ec.agent_name" if "agent_name" in cols else "NULL AS agent_name"
            rows = conn.execute(f"""
                SELECT ec.case_id, ec.policy_number, c.name AS customer_name,
                       ec.reason, ec.priority, ec.briefing_note,
                       ec.assigned_to, {agent_col},
                       ec.created_at, ec.sla_deadline
                FROM escalation_cases ec
                LEFT JOIN customers c ON c.customer_id = ec.customer_id
                WHERE ec.resolved = 0
                ORDER BY
                    CASE ec.priority
                        WHEN 'p1_urgent' THEN 0
                        WHEN 'p2_high'   THEN 1
                        WHEN 'p3_normal' THEN 2
                        WHEN 'p4_low'    THEN 3
                        ELSE 4
                    END,
                    ec.created_at ASC
            """).fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=5)
def get_escalation_resolution_rate() -> dict[str, int]:
    try:
        with _conn() as conn:
            total    = conn.execute("SELECT COUNT(*) FROM escalation_cases").fetchone()[0]
            resolved = conn.execute("SELECT COUNT(*) FROM escalation_cases WHERE resolved=1").fetchone()[0]
        return {"total": total, "resolved": resolved, "open": total - resolved}
    except Exception:
        return {"total": 0, "resolved": 0, "open": 0}


# ── A/B test results ───────────────────────────────────────────────────────────

@st.cache_data(ttl=5)
def get_ab_results() -> pd.DataFrame:
    try:
        with _conn() as conn:
            rows = conn.execute("SELECT * FROM ab_test_results ORDER BY run_at DESC").fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception:
        return pd.DataFrame()


# ── Policies due soon ──────────────────────────────────────────────────────────

@st.cache_data(ttl=5)
def get_policies_due(days: int = 30) -> pd.DataFrame:
    try:
        with _conn() as conn:
            rows = conn.execute(f"""
                SELECT p.policy_number, c.name AS customer_name,
                       c.preferred_channel, c.preferred_language,
                       p.product_name, p.annual_premium,
                       p.renewal_due_date, p.status,
                       JULIANDAY(p.renewal_due_date) - JULIANDAY('now') AS days_to_due
                FROM policies p
                JOIN customers c ON c.customer_id = p.customer_id
                WHERE p.renewal_due_date BETWEEN date('now') AND date('now','+{days} days')
                AND p.status != 'lapsed'
                ORDER BY p.renewal_due_date ASC
            """).fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception:
        return pd.DataFrame()

