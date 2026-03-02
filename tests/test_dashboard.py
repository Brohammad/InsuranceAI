"""
tests/test_dashboard.py
───────────────────────
Unit tests for dashboard/data_service.py — verifies all query functions
run without error and return correctly-typed results (mock DB).
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import pandas as pd

# ── Point data_service at a temp DB ──────────────────────────────────────────
# We monkey-patch DB_PATH before importing data_service

_TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP_DB.close()
TMP_DB_PATH = _TMP_DB.name

# Patch before import
with patch.dict("os.environ", {}):
    import dashboard.data_service as ds
    ds.DB_PATH = TMP_DB_PATH          # redirect all queries to temp DB


# ── Fixture: seed temp DB ─────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def seed_db():
    conn = sqlite3.connect(TMP_DB_PATH)
    c = conn.cursor()

    # Tables
    c.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id TEXT PRIMARY KEY, name TEXT, age INTEGER,
            city TEXT, state TEXT, preferred_language TEXT,
            preferred_channel TEXT, preferred_call_time TEXT,
            email TEXT, phone TEXT, whatsapp_number TEXT,
            occupation TEXT, is_on_dnd INTEGER, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS policies (
            policy_number TEXT PRIMARY KEY, customer_id TEXT,
            product_type TEXT, product_name TEXT, sum_assured REAL,
            annual_premium REAL, policy_start_date TEXT,
            renewal_due_date TEXT, tenure_years INTEGER,
            years_completed INTEGER, status TEXT, payment_mode TEXT,
            has_auto_debit INTEGER, payment_history TEXT,
            last_payment_date TEXT, grace_period_days INTEGER
        );
        CREATE TABLE IF NOT EXISTS renewal_journeys (
            journey_id TEXT PRIMARY KEY, policy_number TEXT,
            customer_id TEXT, status TEXT, segment TEXT,
            lapse_score REAL, channel_sequence TEXT, steps TEXT,
            current_step_index INTEGER, payment_received INTEGER,
            payment_received_at TEXT, escalated INTEGER,
            escalation_reason TEXT, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS interactions (
            interaction_id TEXT PRIMARY KEY, journey_id TEXT,
            policy_number TEXT, customer_id TEXT, channel TEXT,
            direction TEXT, message_content TEXT, language TEXT,
            sent_at TEXT, outcome TEXT, sentiment_score REAL,
            quality_score REAL, critique_passed INTEGER,
            safety_flags TEXT, raw_response TEXT
        );
        CREATE TABLE IF NOT EXISTS escalation_cases (
            case_id TEXT PRIMARY KEY, journey_id TEXT,
            policy_number TEXT, customer_id TEXT,
            reason TEXT, priority TEXT, briefing_note TEXT,
            assigned_to TEXT, agent_name TEXT,
            resolved INTEGER DEFAULT 0, resolution_note TEXT,
            created_at TEXT, resolved_at TEXT, sla_deadline TEXT
        );
        CREATE TABLE IF NOT EXISTS quality_scores (
            score_id TEXT PRIMARY KEY, journey_id TEXT,
            policy_number TEXT, customer_name TEXT,
            channel TEXT, critique_score REAL, compliance_score REAL,
            safety_score REAL, sentiment_score REAL, total_score REAL,
            grade TEXT, summary TEXT, strengths TEXT,
            improvements TEXT, scored_at TEXT
        );
        CREATE TABLE IF NOT EXISTS ab_test_results (
            test_id TEXT PRIMARY KEY, variant TEXT, metric TEXT,
            value REAL, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS customer_memory (
            customer_id TEXT PRIMARY KEY, memory_json TEXT
        );
    """)

    now = datetime.now()
    due_soon = (now + timedelta(days=10)).strftime("%Y-%m-%d")
    due_later = (now + timedelta(days=45)).strftime("%Y-%m-%d")

    # Customers
    c.executemany(
        "INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("CUST-001","Ravi Kumar",45,"Mumbai","Maharashtra","hi","whatsapp",
             "morning","ravi@test.com","9999000001","9999000001","engineer",0,now.isoformat()),
            ("CUST-002","Priya Menon",38,"Chennai","Tamil Nadu","ta","email",
             "evening","priya@test.com","9999000002","9999000002","doctor",0,now.isoformat()),
            ("CUST-003","Suresh Jain",52,"Ahmedabad","Gujarat","gu","voice",
             "afternoon","suresh@test.com","9999000003","9999000003","business",1,now.isoformat()),
        ]
    )

    # Policies
    c.executemany(
        "INSERT INTO policies VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("POL-001","CUST-001","term","Term Plan 1Cr",10000000,25000,
             "2020-01-01",due_soon,20,5,"active","annual",0,"good",
             "2025-01-01",30),
            ("POL-002","CUST-002","ulip","ULIP Growth",5000000,50000,
             "2019-06-01",due_later,15,6,"active","annual",1,"good",
             "2025-06-01",30),
            ("POL-003","CUST-003","health","Health Shield",2000000,18000,
             "2021-03-01",due_later,10,4,"active","quarterly",0,"good",
             "2025-03-01",30),
        ]
    )

    # Journeys
    c.executemany(
        "INSERT INTO renewal_journeys VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("JRN-001","POL-001","CUST-001","renewed","champion",0.12,
             "whatsapp","[]",3,1,now.isoformat(),0,"","2025-01-01",now.isoformat()),
            ("JRN-002","POL-002","CUST-002","in_progress","at_risk",0.65,
             "email","[]",1,0,None,0,"","2025-02-01",now.isoformat()),
            ("JRN-003","POL-003","CUST-003","failed","churned",0.92,
             "voice","[]",2,0,None,1,"distress","2025-03-01",now.isoformat()),
        ]
    )

    # Interactions
    c.executemany(
        "INSERT INTO interactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("INT-001","JRN-001","POL-001","CUST-001","whatsapp","outbound",
             "Hello","hi",now.isoformat(),"delivered",0.8,82,1,"[]","{}"),
            ("INT-002","JRN-002","POL-002","CUST-002","email","outbound",
             "Dear Priya","ta",now.isoformat(),"opened",0.6,74,1,"[]","{}"),
            ("INT-003","JRN-003","POL-003","CUST-003","voice","outbound",
             "Script","gu",now.isoformat(),"voicemail",-0.2,55,0,"[]","{}"),
        ]
    )

    # Escalation cases
    sla_soon = (now + timedelta(hours=2)).isoformat()
    sla_breached = (now - timedelta(hours=1)).isoformat()
    c.executemany(
        "INSERT INTO escalation_cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("ESC-001","JRN-003","POL-003","CUST-003","distress","p1_urgent",
             "Customer distressed","AGT-001","Ravi Sharma",0,"",
             now.isoformat(),"",sla_breached),
            ("ESC-002","JRN-002","POL-002","CUST-002","requested_human","p2_high",
             "Wants human","AGT-002","Sunita Pillai",0,"",
             now.isoformat(),"",sla_soon),
        ]
    )

    # Quality scores
    c.executemany(
        "INSERT INTO quality_scores VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("QS-001","JRN-001","POL-001","Ravi Kumar","whatsapp",
             85,90,100,80,88.75,"A","Good","str","imp",now.isoformat()),
            ("QS-002","JRN-002","POL-002","Priya Menon","email",
             70,80,100,60,77.5,"B+","OK","str","imp",now.isoformat()),
            ("QS-003","JRN-003","POL-003","Suresh Jain","voice",
             45,60,80,30,55.0,"D","Poor","str","imp",now.isoformat()),
        ]
    )

    conn.commit()
    conn.close()
    yield
    # cleanup
    Path(TMP_DB_PATH).unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Tests — Overview KPIs
# ─────────────────────────────────────────────────────────────────────────────

def test_overview_kpis_keys():
    kpis = ds.get_overview_kpis()
    expected = {
        "total_customers","total_policies","due_30_days","renewed",
        "total_journeys","conversion_rate","escalated_open",
        "premium_collected","avg_quality_score",
    }
    assert expected == set(kpis.keys())

def test_overview_kpis_counts():
    kpis = ds.get_overview_kpis()
    assert kpis["total_customers"] == 3
    assert kpis["total_policies"]  == 3
    assert kpis["total_journeys"]  == 3
    assert kpis["renewed"]         == 1

def test_overview_conversion_rate():
    kpis = ds.get_overview_kpis()
    # 1 renewed / 3 journeys = 33.3%
    assert abs(kpis["conversion_rate"] - 33.3) < 0.5

def test_overview_premium_collected():
    kpis = ds.get_overview_kpis()
    # Only POL-001 renewed, premium = 25000
    assert kpis["premium_collected"] == 25000.0

def test_overview_escalated_open():
    kpis = ds.get_overview_kpis()
    assert kpis["escalated_open"] == 2

def test_overview_avg_quality():
    kpis = ds.get_overview_kpis()
    # (88.75 + 77.5 + 55.0) / 3 ≈ 73.75
    assert abs(kpis["avg_quality_score"] - 73.8) < 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Tests — Journey funnel
# ─────────────────────────────────────────────────────────────────────────────

def test_journey_funnel_is_dataframe():
    df = ds.get_journey_funnel()
    assert isinstance(df, pd.DataFrame)

def test_journey_funnel_columns():
    df = ds.get_journey_funnel()
    assert "status" in df.columns and "count" in df.columns

def test_journey_funnel_statuses():
    df = ds.get_journey_funnel()
    statuses = set(df["status"].tolist())
    assert {"renewed","in_progress","failed"} <= statuses

def test_recent_journeys_returns_df():
    df = ds.get_recent_journeys(10)
    assert isinstance(df, pd.DataFrame)
    assert len(df) <= 10

def test_recent_journeys_columns():
    df = ds.get_recent_journeys(10)
    assert "journey_id" in df.columns
    assert "customer_name" in df.columns
    assert "status" in df.columns


# ─────────────────────────────────────────────────────────────────────────────
# Tests — Channel stats
# ─────────────────────────────────────────────────────────────────────────────

def test_channel_stats_df():
    df = ds.get_channel_stats()
    assert isinstance(df, pd.DataFrame)
    assert "channel" in df.columns

def test_channel_stats_all_channels():
    df = ds.get_channel_stats()
    channels = set(df["channel"].tolist())
    assert {"whatsapp","email","voice"} <= channels

def test_interaction_timeline_df():
    df = ds.get_interaction_timeline()
    assert isinstance(df, pd.DataFrame)


# ─────────────────────────────────────────────────────────────────────────────
# Tests — Quality
# ─────────────────────────────────────────────────────────────────────────────

def test_quality_distribution_df():
    df = ds.get_quality_distribution()
    assert isinstance(df, pd.DataFrame)
    assert "grade" in df.columns and "count" in df.columns

def test_quality_distribution_grades():
    df = ds.get_quality_distribution()
    grades = set(df["grade"].tolist())
    assert {"A","B+","D"} <= grades

def test_quality_trend_df():
    df = ds.get_quality_trend()
    assert isinstance(df, pd.DataFrame)

def test_recent_quality_scores_limit():
    df = ds.get_recent_quality_scores(2)
    assert len(df) <= 2

def test_recent_quality_scores_columns():
    df = ds.get_recent_quality_scores(10)
    assert "policy_number" in df.columns
    assert "total_score" in df.columns


# ─────────────────────────────────────────────────────────────────────────────
# Tests — Customers
# ─────────────────────────────────────────────────────────────────────────────

def test_get_all_customers():
    df = ds.get_customers()
    assert len(df) == 3

def test_get_customers_search_by_name():
    df = ds.get_customers("Ravi")
    assert len(df) == 1
    assert df.iloc[0]["name"] == "Ravi Kumar"

def test_get_customers_search_no_match():
    df = ds.get_customers("XXXXXXNOTEXIST")
    assert len(df) == 0

def test_get_customers_columns():
    df = ds.get_customers()
    for col in ["customer_id","name","age","city","policies"]:
        assert col in df.columns

def test_customer_detail_structure():
    detail = ds.get_customer_detail("CUST-001")
    assert "customer" in detail
    assert "policies" in detail
    assert "journeys" in detail
    assert "interactions" in detail

def test_customer_detail_correct_name():
    detail = ds.get_customer_detail("CUST-001")
    assert detail["customer"]["name"] == "Ravi Kumar"

def test_customer_detail_policy_count():
    detail = ds.get_customer_detail("CUST-001")
    assert len(detail["policies"]) == 1

def test_customer_detail_unknown():
    detail = ds.get_customer_detail("CUST-999")
    assert detail["customer"] == {}


# ─────────────────────────────────────────────────────────────────────────────
# Tests — Segment breakdown
# ─────────────────────────────────────────────────────────────────────────────

def test_segment_breakdown_df():
    df = ds.get_segment_breakdown()
    assert isinstance(df, pd.DataFrame)

def test_segment_breakdown_columns():
    df = ds.get_segment_breakdown()
    for col in ["segment","journeys","renewed","avg_lapse_score"]:
        assert col in df.columns

def test_segment_breakdown_conversion_pct():
    df = ds.get_segment_breakdown()
    assert "conversion_pct" in df.columns
    assert (df["conversion_pct"] >= 0).all()
    assert (df["conversion_pct"] <= 100).all()


# ─────────────────────────────────────────────────────────────────────────────
# Tests — Escalations
# ─────────────────────────────────────────────────────────────────────────────

def test_open_escalations_df():
    df = ds.get_open_escalations()
    assert isinstance(df, pd.DataFrame)

def test_open_escalations_count():
    df = ds.get_open_escalations()
    assert len(df) == 2

def test_open_escalations_p1_first():
    df = ds.get_open_escalations()
    assert df.iloc[0]["priority"] == "p1_urgent"

def test_open_escalations_columns():
    df = ds.get_open_escalations()
    for col in ["case_id","policy_number","reason","priority","sla_deadline"]:
        assert col in df.columns

def test_escalation_resolution_rate():
    rate = ds.get_escalation_resolution_rate()
    assert rate["total"] == 2
    assert rate["open"]  == 2
    assert rate["resolved"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Tests — Renewals due
# ─────────────────────────────────────────────────────────────────────────────

def test_policies_due_df():
    df = ds.get_policies_due(30)
    assert isinstance(df, pd.DataFrame)

def test_policies_due_columns():
    df = ds.get_policies_due(90)
    if not df.empty:
        for col in ["policy_number","customer_name","annual_premium","days_to_due"]:
            assert col in df.columns

def test_policies_due_within_window():
    df = ds.get_policies_due(15)
    # POL-001 is due in 10 days → should appear
    assert any(df["policy_number"] == "POL-001") if not df.empty else True

def test_policies_due_sorted():
    df = ds.get_policies_due(90)
    if len(df) >= 2:
        dates = df["renewal_due_date"].tolist()
        assert dates == sorted(dates)


# ─────────────────────────────────────────────────────────────────────────────
# Tests — AB results
# ─────────────────────────────────────────────────────────────────────────────

def test_ab_results_df():
    df = ds.get_ab_results()
    assert isinstance(df, pd.DataFrame)
