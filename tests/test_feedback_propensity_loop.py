"""
tests/test_feedback_propensity_loop.py
──────────────────────────────────────
Tests for the closed feedback → propensity refresh loop.

Covers:
  1. refresh_from_feedback() skips when event count < threshold
  2. refresh_from_feedback() builds few-shot block when events exist
  3. FeedbackLoopAgent.run() sets propensity_prompt_refreshed=True after threshold
  4. Few-shot block is prepended to propensity prompt in run()
  5. run_batch_with_feedback() wires feedback after batch journeys
"""

from __future__ import annotations

import sqlite3
import tempfile
import os
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────

def _make_temp_db() -> tuple[str, sqlite3.Connection]:
    """Create a temp SQLite DB with the tables needed by tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
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
        );
        CREATE TABLE IF NOT EXISTS renewal_journeys (
            journey_id    TEXT PRIMARY KEY,
            policy_number TEXT,
            customer_id   TEXT,
            lapse_score   REAL DEFAULT 50,
            segment       TEXT,
            status        TEXT DEFAULT 'pending'
        );
        CREATE TABLE IF NOT EXISTS interactions (
            interaction_id TEXT PRIMARY KEY,
            journey_id     TEXT,
            policy_number  TEXT,
            customer_id    TEXT,
            channel        TEXT,
            outcome        TEXT,
            sent_at        TEXT
        );
        CREATE TABLE IF NOT EXISTS quality_scores (
            score_id    TEXT PRIMARY KEY,
            journey_id  TEXT,
            total_score REAL
        );
    """)
    conn.commit()
    return path, conn


def _insert_feedback_events(conn, n_positive=5, n_negative=5):
    """Insert fake strong-signal feedback events."""
    import uuid
    from datetime import datetime
    for i in range(n_positive):
        conn.execute(
            "INSERT INTO feedback_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f"FB-POS-{i}", f"J-{i}", f"POL-{i:04d}", f"CUST-{i}",
             "strong_positive", "payment_made", -20, 70.0, 50.0, 85.0,
             datetime.now().isoformat())
        )
    for i in range(n_negative):
        conn.execute(
            "INSERT INTO feedback_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f"FB-NEG-{i}", f"J-{100+i}", f"POL-{100+i:04d}", f"CUST-{100+i}",
             "strong_negative", "opt_out", +20, 40.0, 60.0, 45.0,
             datetime.now().isoformat())
        )
    conn.commit()


# ── Test 1: skip when below threshold ────────────────────────────────────────

def test_refresh_skips_below_threshold():
    """refresh_from_feedback returns False when events < threshold."""
    db_path, conn = _make_temp_db()
    _insert_feedback_events(conn, n_positive=2, n_negative=2)   # only 4 strong events
    conn.close()

    with patch("agents.layer1_strategic.propensity.settings") as mock_settings:
        mock_settings.abs_db_path = db_path
        from agents.layer1_strategic import propensity as prop_mod
        # Reset few-shot cache
        prop_mod._FEEDBACK_FEW_SHOT = ""

        from agents.layer1_strategic.propensity import PropensityAgent
        pa = PropensityAgent.__new__(PropensityAgent)
        pa.client = None
        pa.model  = None

        result = pa.refresh_from_feedback(min_events=10)

    assert result is False
    assert prop_mod._FEEDBACK_FEW_SHOT == ""
    os.unlink(db_path)


# ── Test 2: builds few-shot block above threshold ─────────────────────────────

def test_refresh_builds_few_shot_block():
    """refresh_from_feedback populates _FEEDBACK_FEW_SHOT with paid/lapsed examples."""
    db_path, conn = _make_temp_db()
    # Insert journeys so the LEFT JOIN has segment data
    for i in range(10):
        conn.execute(
            "INSERT INTO renewal_journeys VALUES (?,?,?,?,?,?)",
            (f"J-{i}", f"POL-{i:04d}", f"CUST-{i}", 50.0, "at_risk", "pending")
        )
    for i in range(10):
        conn.execute(
            "INSERT INTO renewal_journeys VALUES (?,?,?,?,?,?)",
            (f"J-{100+i}", f"POL-{100+i:04d}", f"CUST-{100+i}", 70.0, "churned", "pending")
        )
    conn.commit()
    _insert_feedback_events(conn, n_positive=6, n_negative=6)
    conn.close()

    with patch("agents.layer1_strategic.propensity.settings") as mock_settings:
        mock_settings.abs_db_path = db_path
        from agents.layer1_strategic import propensity as prop_mod
        prop_mod._FEEDBACK_FEW_SHOT = ""

        from agents.layer1_strategic.propensity import PropensityAgent
        pa = PropensityAgent.__new__(PropensityAgent)
        pa.client = None
        pa.model  = None

        result = pa.refresh_from_feedback(min_events=10)

    assert result is True
    assert "✅ PAID" in prop_mod._FEEDBACK_FEW_SHOT
    assert "❌ LAPSED" in prop_mod._FEEDBACK_FEW_SHOT
    assert "REAL OUTCOME EXAMPLES" in prop_mod._FEEDBACK_FEW_SHOT
    os.unlink(db_path)


# ── Test 3: few-shot block prepended to prompt ────────────────────────────────

def test_few_shot_prepended_to_prompt():
    """PropensityAgent.run() prepends the few-shot block to the prompt sent to Gemini."""
    from agents.layer1_strategic import propensity as prop_mod

    # Inject a fake few-shot block
    fake_block = "── REAL OUTCOME EXAMPLES ──\n  ✅ PAID policy=TEST\n"
    prop_mod._FEEDBACK_FEW_SHOT = fake_block

    mock_response = MagicMock()
    mock_response.text = '{"lapse_score": 55, "intervention_intensity": "moderate", "top_reasons": ["test"], "recommended_actions": ["test"], "reasoning": "unit test"}'

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    from agents.layer1_strategic.propensity import PropensityAgent, PropensityResult
    from core.models import Customer, Policy, CustomerSegment, Channel, ProductType

    pa = PropensityAgent.__new__(PropensityAgent)
    pa.client = mock_client
    pa.model  = "test-model"

    customer = Customer(
        customer_id="CUST-001", name="Test User", age=35, phone="+919876543210",
        email="test@test.com",
        preferred_language=__import__("core.models", fromlist=["Language"]).Language.ENGLISH,
        preferred_channel=Channel.WHATSAPP, occupation="Engineer",
        annual_income=600000, city="Mumbai", state="Maharashtra",
        is_on_dnd=False, gender="M",
        preferred_call_time="morning", whatsapp_number="+919876543210",
    )
    policy = Policy(
        policy_id="POL-001", policy_number="SLI-0001", customer_id="CUST-001",
        product_type=ProductType.TERM, product_name="Suraksha Term Plan",
        annual_premium=15000, sum_assured=1000000,
        tenure_years=20, years_completed=5,
        policy_start_date=date.today() - timedelta(days=365 * 5),
        renewal_due_date=date.today() + timedelta(days=10),
        has_auto_debit=False,
        payment_history=["on_time", "on_time", "missed"],
    )

    pa.run(customer, policy, segment="at_risk")

    call_args = mock_client.models.generate_content.call_args
    prompt_used = call_args[1]["contents"] if call_args[1] else call_args[0][1]
    assert fake_block in prompt_used

    # Reset cache
    prop_mod._FEEDBACK_FEW_SHOT = ""


# ── Test 4: FeedbackSummary has propensity_prompt_refreshed field ─────────────

def test_feedback_summary_has_refresh_flag():
    """FeedbackSummary dataclass includes propensity_prompt_refreshed field."""
    from agents.layer4_learning.feedback_loop import FeedbackSummary
    summary = FeedbackSummary()
    assert hasattr(summary, "propensity_prompt_refreshed")
    assert summary.propensity_prompt_refreshed is False


# ── Test 5: FeedbackLoopAgent sets refresh flag when threshold met ────────────

def test_feedback_loop_sets_refresh_flag_when_threshold_met():
    """FeedbackLoopAgent.run() sets propensity_prompt_refreshed=True when enough events."""
    db_path, conn = _make_temp_db()

    # Seed a journey + interaction so the feedback loop has something to process
    conn.execute(
        "INSERT INTO renewal_journeys VALUES (?,?,?,?,?,?)",
        ("J-MAIN", "SLI-9999", "CUST-MAIN", 60.0, "at_risk", "pending")
    )
    from datetime import datetime
    conn.execute(
        "INSERT INTO interactions VALUES (?,?,?,?,?,?,?)",
        ("INT-001", "J-MAIN", "SLI-9999", "CUST-MAIN", "whatsapp", "payment_made",
         datetime.now().isoformat())
    )
    # Pre-seed 10 strong-signal events so refresh threshold is met
    _insert_feedback_events(conn, n_positive=6, n_negative=6)
    conn.commit()
    conn.close()

    with patch("agents.layer4_learning.feedback_loop.settings") as mock_fb_settings, \
         patch("agents.layer1_strategic.propensity.settings") as mock_prop_settings:

        mock_fb_settings.abs_db_path   = db_path
        mock_prop_settings.abs_db_path = db_path

        from agents.layer4_learning.feedback_loop import FeedbackLoopAgent
        from agents.layer1_strategic import propensity as prop_mod
        prop_mod._FEEDBACK_FEW_SHOT = ""

        agent = FeedbackLoopAgent.__new__(FeedbackLoopAgent)
        agent._db_path = db_path

        _events, summary = agent.run()

    assert summary.propensity_prompt_refreshed is True
    os.unlink(db_path)


# ── Test 6: run_batch_with_feedback passes feedback=None when no pairs ─────────

def test_run_batch_no_pairs_returns_empty():
    """run_batch_with_feedback with empty list returns empty journeys list."""
    with patch("agents.layer4_learning.feedback_loop.settings") as mock_settings:
        mock_settings.abs_db_path = ":memory:"
        with patch("agents.layer1_strategic.orchestrator.build_layer1_graph"):
            from agents.layer1_strategic.orchestrator import run_batch_with_feedback
            result = run_batch_with_feedback([], run_feedback_loop=False)

    assert result["journeys"] == []
    assert result["feedback"] is None
    assert result["prompt_refreshed"] is False


# ── Test 7: refresh_from_feedback is idempotent ────────────────────────────────

def test_refresh_idempotent():
    """Calling refresh_from_feedback twice keeps the cache updated (not doubled)."""
    db_path, conn = _make_temp_db()
    for i in range(5):
        conn.execute(
            "INSERT INTO renewal_journeys VALUES (?,?,?,?,?,?)",
            (f"J-{i}", f"POL-{i:04d}", f"CUST-{i}", 50.0, "at_risk", "pending")
        )
    conn.commit()
    _insert_feedback_events(conn, n_positive=6, n_negative=5)
    conn.close()

    with patch("agents.layer1_strategic.propensity.settings") as mock_settings:
        mock_settings.abs_db_path = db_path
        from agents.layer1_strategic import propensity as prop_mod
        prop_mod._FEEDBACK_FEW_SHOT = ""

        from agents.layer1_strategic.propensity import PropensityAgent
        pa = PropensityAgent.__new__(PropensityAgent)
        pa.client = None
        pa.model  = None

        pa.refresh_from_feedback(min_events=10)
        block_first = prop_mod._FEEDBACK_FEW_SHOT

        pa.refresh_from_feedback(min_events=10)
        block_second = prop_mod._FEEDBACK_FEW_SHOT

    # Should be same content (refreshed from same DB)
    assert block_first == block_second
    prop_mod._FEEDBACK_FEW_SHOT = ""
    os.unlink(db_path)
