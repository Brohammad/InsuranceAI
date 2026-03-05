"""
dashboard/app.py
────────────────
Project RenewAI — Admin Dashboard (Streamlit multi-page)

Run:
    streamlit run dashboard/app.py

Pages (sidebar):
  1. 📊 Overview        — KPI headline cards + funnel + timeline
  2. 🔄 Journeys        — Journey table, segment breakdown, channel stats
  3. 👥 Customers       — Search, drill-down, policy detail
  4. ✅ Quality         — Score distribution, trend, grade table
  5. 🚨 Escalations     — Open queue with SLA RAG status
  6. 📅 Renewals Due    — Policies expiring soon
  7. ⚙️  Settings       — .env key visibility (masked)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ── Make project root importable ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

from dashboard.data_service import (
    get_overview_kpis,
    get_journey_funnel,
    get_recent_journeys,
    get_channel_stats,
    get_interaction_timeline,
    get_quality_distribution,
    get_quality_trend,
    get_recent_quality_scores,
    get_customers,
    get_customer_detail,
    get_segment_breakdown,
    get_open_escalations,
    get_escalation_resolution_rate,
    get_ab_results,
    get_policies_due,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="RenewAI Admin",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Metric cards */
div[data-testid="metric-container"] {
    background: #1e2130;
    border: 1px solid #2e3250;
    border-radius: 10px;
    padding: 16px 20px;
}
div[data-testid="metric-container"] label {
    color: #8892b0 !important;
    font-size: 0.78rem !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
div[data-testid="metric-container"] [data-testid="stMetricValue"] {
    font-size: 1.9rem !important;
    font-weight: 700;
}
/* Sidebar brand */
.sidebar-brand {
    font-size: 1.2rem;
    font-weight: 700;
    color: #ccd6f6;
    padding: 0.4rem 0 1rem 0;
    border-bottom: 1px solid #2e3250;
    margin-bottom: 1rem;
}
/* Priority badges */
.badge-p1 { background:#ff4b4b; color:white; border-radius:4px; padding:2px 8px; font-size:0.75rem; font-weight:700; }
.badge-p2 { background:#ff8c00; color:white; border-radius:4px; padding:2px 8px; font-size:0.75rem; font-weight:700; }
.badge-p3 { background:#0068c9; color:white; border-radius:4px; padding:2px 8px; font-size:0.75rem; font-weight:700; }
.badge-p4 { background:#21c354; color:white; border-radius:4px; padding:2px 8px; font-size:0.75rem; font-weight:700; }
.badge-sla { background:#ff4b4b; color:white; border-radius:4px; padding:2px 8px; font-size:0.75rem; font-weight:700; }
</style>
""", unsafe_allow_html=True)


# ── Auto-seed DB (Streamlit Community Cloud) ──────────────────────────────────
# Bump this version string whenever the DB schema changes.
# On Cloud the filesystem is ephemeral — each cold-start gets a fresh container,
# so the DB is always re-seeded. The version file ensures we also reseed when
# schema changes land mid-session (e.g. after a redeploy with warm cache).
_DB_SCHEMA_VERSION = "v9"

@st.cache_resource(show_spinner="Initialising database…")
def _ensure_db() -> None:
    """
    Seed (or re-seed) the SQLite DB so it always matches the current schema.
    On Streamlit Cloud the filesystem is ephemeral — DB is always empty on
    cold-start.  This function is cached with @st.cache_resource so it runs
    exactly ONCE per container lifetime (not once per user session).
    """
    import sys as _sys
    import importlib.util as _ilu
    from pathlib import Path as _Path

    _root = _Path(__file__).resolve().parent.parent
    _db   = _root / "data" / "renewai.db"
    _ver  = _root / "data" / ".schema_version"

    # Wipe DB if schema version has changed (or it doesn't exist)
    _stale = (not _db.exists()) or (not _ver.exists()) or (_ver.read_text().strip() != _DB_SCHEMA_VERSION)
    if _stale:
        if _db.exists():
            _db.unlink()
        _db.parent.mkdir(parents=True, exist_ok=True)

        # Run seed
        if str(_root) not in _sys.path:
            _sys.path.insert(0, str(_root))
        _spec = _ilu.spec_from_file_location("seed", _root / "data" / "seed.py")
        _mod  = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _mod.seed()

        # Write version sentinel
        _ver.write_text(_DB_SCHEMA_VERSION)

    # Run initial e2e pass right after seeding so there is fresh data
    # on the very first page load (seed only gives static baseline).
    _run_e2e_in_process(_root)


def _maybe_run_e2e() -> None:
    """
    Run _run_e2e_in_process() at most once every 30 minutes per session,
    and always on the very first page load of each session.
    This keeps Cloud data fresh without hammering the DB on every rerun.
    """
    import time as _time
    _now = _time.time()
    _last = st.session_state.get("_e2e_last_run", 0)
    _interval = 30 * 60  # 30 minutes
    if _now - _last >= _interval:
        _run_e2e_in_process()
        st.session_state["_e2e_last_run"] = _now


def _run_e2e_in_process(root=None) -> dict:
    """
    Run a full mock e2e pass (all 5 layers) for the 3 most urgent policies.
    Executes entirely in-process — no subprocesses, no real API calls.
    Returns a summary dict.
    """
    import json, sqlite3, uuid
    from datetime import date, datetime
    from pathlib import Path
    from unittest.mock import patch, MagicMock

    if root is None:
        root = Path(__file__).resolve().parent.parent

    db_path = str(root / "data" / "renewai.db")
    summary = {"journeys": 0, "interactions": 0, "quality_scores": 0,
                "feedback_events": 0, "errors": []}

    # ── Pick up to 3 policies that have NO journey in the last 24 hours ─────
    # This prevents the same 3 policies from being skipped/duplicated on every
    # Cloud visit when the e2e runner fires again on a warm container.
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        targets = conn.execute("""
            SELECT c.customer_id, c.name, p.policy_number,
                   CAST(julianday(p.renewal_due_date) - julianday('now') AS INT) AS days_left
            FROM customers c
            JOIN policies p ON p.customer_id = c.customer_id
            WHERE p.policy_number NOT IN (
                SELECT DISTINCT policy_number FROM renewal_journeys
                WHERE created_at >= datetime('now', '-24 hours')
            )
            ORDER BY days_left ASC LIMIT 3
        """).fetchall()
        # Fallback: if all policies have recent journeys, just pick the 3 most urgent
        if not targets:
            targets = conn.execute("""
                SELECT c.customer_id, c.name, p.policy_number,
                       CAST(julianday(p.renewal_due_date) - julianday('now') AS INT) AS days_left
                FROM customers c JOIN policies p ON p.customer_id = c.customer_id
                ORDER BY days_left ASC LIMIT 3
            """).fetchall()
        conn.close()
    except Exception as e:
        summary["errors"].append(f"DB read: {e}")
        return summary

    if not targets:
        return summary

    # ── Mock Gemini helper ───────────────────────────────────────────────────
    def _mock_client(responses):
        idx = [0]
        def se(*a, **kw):
            m = MagicMock(); m.text = responses[idx[0] % len(responses)]; idx[0] += 1; return m
        c = MagicMock(); c.models.generate_content.side_effect = se; return c

    paid_count = 0  # track how many journeys we mark as paid this run

    for row_idx, row in enumerate(targets):
        cid, name, pid, days = row["customer_id"], row["name"], row["policy_number"], row["days_left"]
        intensity = "urgent" if days <= 3 else ("intensive" if days <= 7 else "moderate")
        lapse     = 85 if days <= 5 else 55
        ch_seq    = ["whatsapp", "email", "voice"] if days <= 5 else ["whatsapp", "email"]

        seg_j  = json.dumps({"segment": "high_risk", "recommended_tone": "empathetic",
                              "recommended_strategy": "renewal_reminder", "risk_flag": "high",
                              "reasoning": "Urgent."})
        prop_j = json.dumps({"lapse_score": lapse, "intervention_intensity": intensity,
                              "top_reasons": ["due soon"], "recommended_actions": ch_seq,
                              "reasoning": "Mock."})
        tim_j  = json.dumps({"best_contact_window": "18:00-20:00", "best_days": ["Monday"],
                              "salary_day_flag": True, "urgency_override": days <= 3,
                              "reasoning": "Mock."})
        ch_j   = json.dumps({"channel_sequence": ch_seq, "reasoning": "Mock."})

        mc = _mock_client([seg_j, prop_j, tim_j, ch_j])

        try:
            # Layer 1
            with patch("agents.layer1_strategic.segmentation.get_gemini_client",    return_value=mc), \
                 patch("agents.layer1_strategic.propensity.get_gemini_client",       return_value=mc), \
                 patch("agents.layer1_strategic.timing.get_gemini_client",           return_value=mc), \
                 patch("agents.layer1_strategic.channel_selector.get_gemini_client", return_value=mc):
                from core.database import get_customer, get_policy
                from agents.layer1_strategic.orchestrator import run_layer1
                cust = get_customer(cid); pol = get_policy(pid)
                if not cust or not pol:
                    continue
                journey = run_layer1(cust, pol)
            summary["journeys"] += 1

            # Layer 2
            msg_mock = MagicMock(); msg_mock.text = f"Dear {name}, your policy is due. Renew now."
            with patch("agents.layer2_execution.whatsapp_agent.get_gemini_client") as wm, \
                 patch("agents.layer2_execution.email_agent.get_gemini_client")    as em, \
                 patch("agents.layer2_execution.voice_agent.get_gemini_client")    as vm, \
                 patch("agents.layer2_execution.whatsapp_agent.settings") as ws, \
                 patch("agents.layer2_execution.email_agent.settings")    as es, \
                 patch("agents.layer2_execution.voice_agent.settings")    as vs:
                for ms in (ws, es, vs):
                    ms.mock_delivery = True; ms.model_execution = "gemini-2.5-flash"
                for mc2 in (wm, em, vm):
                    c2 = MagicMock(); c2.models.generate_content.return_value = msg_mock
                    mc2.return_value = c2
                from agents.layer2_execution.dispatcher import Layer2Dispatcher
                disp = Layer2Dispatcher()
                res  = disp.run_journey(journey)
            n_steps = len(res.get("steps", [])) if isinstance(res, dict) else 0
            summary["interactions"] += n_steps

            # Layer 3
            from agents.layer3_quality.quality_scoring import QualityScoringAgent
            from agents.layer3_quality.critique_agent import CritiqueResult
            from agents.layer3_quality.compliance_agent import ComplianceResult
            from agents.layer3_quality.safety_agent import SafetyResult, SafetyFlag
            from agents.layer3_quality.sentiment_agent import SentimentResult, SentimentPolarity, CustomerIntent
            qs_agent = QualityScoringAgent()
            qs = qs_agent.score(
                journey_id=journey.journey_id, policy_number=pid,
                customer_name=name, channel="whatsapp",
                critique=CritiqueResult(approved=True, tone_score=8, accuracy_score=8,
                                         personalisation_score=7, conversion_likelihood=8),
                compliance=ComplianceResult(overall_pass=True, rules_checked=3,
                                             rules_failed=0, failed_rules=[], passed_rules=[]),
                safety=SafetyResult(flag=SafetyFlag.CLEAR, confidence=1.0),
                sentiment=SentimentResult(polarity=SentimentPolarity.POSITIVE,
                                           score=0.65, intent=CustomerIntent.INTENDING_TO_PAY),
            )
            qs_agent.save_score(qs)
            summary["quality_scores"] += 1

            # Mark every other journey (index 0, 2, …) as payment received
            # so conversion_rate and premium_collected are always non-zero
            if row_idx % 2 == 0:
                try:
                    from core.database import mark_payment_received
                    mark_payment_received(journey.journey_id)
                    paid_count += 1
                except Exception as pe:
                    summary["errors"].append(f"mark_payment {name}: {pe}")

        except Exception as e:
            summary["errors"].append(f"{name}: {e}")
            continue

    # Layer 4 — feedback loop
    try:
        from agents.layer4_learning.feedback_loop import FeedbackLoopAgent
        fl = FeedbackLoopAgent()
        events, fl_summary = fl.run()
        summary["feedback_events"] = fl_summary.total_events
    except Exception as e:
        summary["errors"].append(f"L4: {e}")

    summary["payments_received"] = paid_count
    return summary

_ensure_db()          # runs once per container — seeds DB + initial e2e pass
_maybe_run_e2e()      # runs every 30 min per session — keeps data fresh on Cloud


# ── Sidebar nav ───────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="sidebar-brand">🛡️ RenewAI Admin</div>', unsafe_allow_html=True)
    page = st.radio(
        "Navigate",
        [
            "📊 Overview",
            "🔄 Journeys",
            "👥 Customers",
            "✅ Quality",
            "🚨 Escalations",
            "📅 Renewals Due",
            "⚙️  Settings",
        ],
        label_visibility="collapsed",
    )
    st.markdown("---")

    # ── Live refresh controls ─────────────────────────────────────────────────
    st.markdown("**🔄 Live Data**")
    auto_refresh = st.toggle("Auto-refresh (5s)", value=False, key="auto_refresh")
    if st.button("🔃 Refresh Now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")

    # ── Run E2E Pipeline ──────────────────────────────────────────────────────
    st.markdown("**⚡ Pipeline**")
    if st.button("▶ Run E2E Pipeline", use_container_width=True, type="primary"):
        with st.spinner("Running all 5 layers…"):
            result = _run_e2e_in_process()
        st.cache_data.clear()
        if result["errors"]:
            st.warning(f"Completed with {len(result['errors'])} error(s): {result['errors'][0]}")
        else:
            st.success(
                f"✅ Done!\n"
                f"• {result['journeys']} journeys\n"
                f"• {result['interactions']} interactions\n"
                f"• {result['quality_scores']} quality scores\n"
                f"• {result['feedback_events']} feedback events"
            )
        st.rerun()

    st.markdown("---")
    st.caption(f"Suraksha Life Insurance\nProject RenewAI\n\n*{datetime.now().strftime('%d %b %Y, %H:%M')}*")

# ── Auto-refresh (fires AFTER the page renders) ───────────────────────────────
# Use JS meta-refresh instead of time.sleep() — sleep blocks the Streamlit
# worker thread on Cloud and can cause the app to appear frozen/unresponsive.
if st.session_state.get("auto_refresh"):
    st.markdown(
        '<meta http-equiv="refresh" content="10">',
        unsafe_allow_html=True,
    )
    st.cache_data.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────────────────────────────────────────

PRIORITY_LABEL = {
    "p1_urgent": "🔴 P1 Urgent",
    "p2_high":   "🟠 P2 High",
    "p3_normal": "🔵 P3 Normal",
    "p4_low":    "🟢 P4 Low",
}

GRADE_COLOR = {
    "A+": "#21c354", "A": "#29b09d",
    "B+": "#0068c9", "B": "#6eb7f5",
    "C":  "#ff8c00", "D": "#ff4b4b", "F": "#7c0a02",
}

STATUS_COLOR = {
    "renewed":     "#21c354",
    "in_progress": "#0068c9",
    "pending":     "#ff8c00",
    "failed":      "#ff4b4b",
    "lapsed":      "#888888",
}

def _pct_bar(val: float, color: str = "#0068c9") -> str:
    """Tiny inline progress bar as HTML."""
    w = min(max(int(val), 0), 100)
    return (
        f'<div style="background:#2e3250;border-radius:4px;height:8px;width:120px;">'
        f'<div style="background:{color};width:{w}%;height:8px;border-radius:4px;"></div></div>'
        f'<span style="font-size:0.8rem;color:#ccd6f6;"> {val:.1f}%</span>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 1 — Overview
# ─────────────────────────────────────────────────────────────────────────────

if page == "📊 Overview":
    st.title("📊 Overview")
    st.caption("Live metrics from the RenewAI database")

    kpis = get_overview_kpis()

    # Row 1 — headline cards
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Customers",  f"{kpis['total_customers']:,}")
    c2.metric("Total Policies",   f"{kpis['total_policies']:,}")
    c3.metric("Due in 30 Days",   f"{kpis['due_30_days']:,}")
    c4.metric("Journeys Started", f"{kpis['total_journeys']:,}")
    c5.metric("Renewed ✅",        f"{kpis['renewed']:,}")

    st.markdown("---")

    # Row 2
    c1, c2, c3, c4 = st.columns(4)
    conv = kpis["conversion_rate"]
    delta_color = "normal" if conv >= 60 else "inverse"
    c1.metric("Conversion Rate",    f"{conv}%", delta=f"{conv-60:.1f}% vs target", delta_color=delta_color)
    c2.metric("Open Escalations",   f"{kpis['escalated_open']}", delta_color="inverse" if kpis['escalated_open'] > 5 else "off")
    c3.metric("Premium Collected",  f"₹{kpis['premium_collected']:,.0f}")
    c4.metric("Avg Quality Score",  f"{kpis['avg_quality_score']}/100")

    st.markdown("---")

    col_left, col_right = st.columns([1, 1])

    # Journey funnel
    with col_left:
        st.subheader("Journey Status Funnel")
        funnel_df = get_journey_funnel()
        if not funnel_df.empty:
            order = ["pending","in_progress","renewed","failed","lapsed"]
            funnel_df["_order"] = funnel_df["status"].apply(
                lambda s: order.index(s) if s in order else 99
            )
            funnel_df = funnel_df.sort_values("_order")
            fig = px.funnel(
                funnel_df, x="count", y="status",
                color_discrete_sequence=["#0068c9","#29b09d","#21c354","#ff4b4b","#888888"],
            )
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#ccd6f6",
                margin=dict(l=10, r=10, t=10, b=10),
                height=280,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No journey data yet.")

    # Segment breakdown
    with col_right:
        st.subheader("Segment Breakdown")
        seg_df = get_segment_breakdown()
        if not seg_df.empty:
            fig = px.bar(
                seg_df, x="segment", y="journeys",
                color="conversion_pct",
                color_continuous_scale="Teal",
                labels={"journeys": "Journeys", "conversion_pct": "Conv %"},
            )
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#ccd6f6",
                margin=dict(l=10, r=10, t=10, b=10),
                height=280,
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No segment data yet.")

    # Interaction timeline
    st.subheader("Interaction Volume by Channel (Daily)")
    tl_df = get_interaction_timeline()
    if not tl_df.empty:
        fig = px.area(
            tl_df, x="day", y="count", color="channel",
            color_discrete_map={"whatsapp": "#25d366", "email": "#0068c9", "voice": "#ff8c00"},
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#ccd6f6",
            margin=dict(l=10, r=10, t=10, b=10),
            height=240,
            legend=dict(orientation="h", y=1.02),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No interaction data yet.")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 2 — Journeys
# ─────────────────────────────────────────────────────────────────────────────

elif page == "🔄 Journeys":
    st.title("🔄 Renewal Journeys")

    col_a, col_b = st.columns([1, 1])

    with col_a:
        st.subheader("Channel Performance")
        ch_df = get_channel_stats()
        if not ch_df.empty:
            fig = go.Figure()
            fig.add_trace(go.Bar(
                name="Avg Quality",
                x=ch_df["channel"], y=ch_df["avg_quality"],
                marker_color="#0068c9",
            ))
            fig.add_trace(go.Bar(
                name="Avg Sentiment",
                x=ch_df["channel"], y=ch_df["avg_sentiment"],
                marker_color="#21c354",
            ))
            fig.update_layout(
                barmode="group",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#ccd6f6",
                margin=dict(l=10, r=10, t=10, b=10),
                height=260,
                legend=dict(orientation="h", y=1.02),
            )
            st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.subheader("Segment Conversion")
        seg_df = get_segment_breakdown()
        if not seg_df.empty:
            fig = px.scatter(
                seg_df,
                x="avg_lapse_score", y="conversion_pct",
                size="journeys", color="segment",
                labels={"avg_lapse_score": "Avg Lapse Score", "conversion_pct": "Conversion %"},
                size_max=50,
            )
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#ccd6f6",
                margin=dict(l=10, r=10, t=10, b=10),
                height=260,
            )
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Recent Journeys")
    jdf = get_recent_journeys(100)
    if not jdf.empty:
        # Status filter
        statuses = ["All"] + sorted(jdf["status"].dropna().unique().tolist())
        sel_status = st.selectbox("Filter by status", statuses, key="j_status")
        if sel_status != "All":
            jdf = jdf[jdf["status"] == sel_status]

        # Color status column
        def _color_status(val: str) -> str:
            c = STATUS_COLOR.get(val, "#888")
            return f"color: {c}; font-weight: 600"

        st.dataframe(
            jdf.style.map(_color_status, subset=["status"]),
            use_container_width=True,
            height=420,
        )
    else:
        st.info("No journey data yet.")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 3 — Customers
# ─────────────────────────────────────────────────────────────────────────────

elif page == "👥 Customers":
    st.title("👥 Customers")

    search = st.text_input("🔍 Search by name / phone / email", "")
    cdf = get_customers(search)

    st.caption(f"{len(cdf)} customer(s) found")

    if not cdf.empty:
        selected = st.dataframe(
            cdf[["customer_id","name","age","city","state","preferred_language",
                 "preferred_channel","policies","is_on_dnd"]],
            use_container_width=True,
            height=320,
            on_select="rerun",
            selection_mode="single-row",
        )

        # Drill-down
        sel_rows = selected.selection.rows if hasattr(selected, "selection") else []
        if sel_rows:
            cid = cdf.iloc[sel_rows[0]]["customer_id"]
            detail = get_customer_detail(cid)
            cust   = detail["customer"]
            if cust:
                st.divider()
                st.subheader(f"👤 {cust.get('name','?')} — {cid}")

                dc1, dc2, dc3 = st.columns(3)
                dc1.markdown(f"**Age:** {cust.get('age')}")
                dc1.markdown(f"**City:** {cust.get('city')}, {cust.get('state')}")
                dc1.markdown(f"**Language:** {cust.get('preferred_language','en')}")
                dc2.markdown(f"**Phone:** {cust.get('phone')}")
                dc2.markdown(f"**Email:** {cust.get('email')}")
                dc2.markdown(f"**WhatsApp:** {cust.get('whatsapp_number')}")
                dc3.markdown(f"**Channel:** {cust.get('preferred_channel')}")
                dc3.markdown(f"**DND:** {'🚫 Yes' if cust.get('is_on_dnd') else '✅ No'}")
                dc3.markdown(f"**Call Time:** {cust.get('preferred_call_time','any')}")

                st.markdown("**Policies**")
                if detail["policies"]:
                    st.dataframe(
                        pd.DataFrame(detail["policies"])[
                            ["policy_number","product_name","annual_premium",
                             "renewal_due_date","status","has_auto_debit"]
                        ],
                        use_container_width=True, height=160,
                    )

                st.markdown("**Recent Interactions** (last 20)")
                if detail["interactions"]:
                    idf = pd.DataFrame(detail["interactions"])
                    st.dataframe(
                        idf[["sent_at","channel","direction","outcome",
                             "sentiment_score","quality_score"]],
                        use_container_width=True, height=200,
                    )
    else:
        st.info("No customers found.")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 4 — Quality
# ─────────────────────────────────────────────────────────────────────────────

elif page == "✅ Quality":
    st.title("✅ Quality Scores")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Grade Distribution")
        gdf = get_quality_distribution()
        if not gdf.empty:
            gdf["color"] = gdf["grade"].map(GRADE_COLOR).fillna("#888")
            fig = px.bar(
                gdf, x="grade", y="count", color="grade",
                color_discrete_map=GRADE_COLOR,
            )
            fig.update_layout(
                showlegend=False,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#ccd6f6",
                margin=dict(l=10, r=10, t=10, b=10),
                height=260,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No quality data yet.")

    with col2:
        st.subheader("Score Trend")
        qtdf = get_quality_trend()
        if not qtdf.empty:
            fig = px.line(
                qtdf, x="day", y="avg_score",
                markers=True,
                color_discrete_sequence=["#0068c9"],
            )
            fig.add_hline(y=75, line_dash="dash", line_color="#ff8c00",
                          annotation_text="Target 75", annotation_position="bottom right")
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#ccd6f6",
                margin=dict(l=10, r=10, t=10, b=10),
                height=260,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No quality trend data yet.")

    st.subheader("Recent Score Records")
    qdf = get_recent_quality_scores(50)
    if not qdf.empty:
        def _grade_color(val: str) -> str:
            c = GRADE_COLOR.get(val, "#888")
            return f"color: {c}; font-weight: 700"

        st.dataframe(
            qdf.style.map(_grade_color, subset=["grade"]),
            use_container_width=True, height=380,
        )
    else:
        st.info("No scored interactions yet.")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 5 — Escalations
# ─────────────────────────────────────────────────────────────────────────────

elif page == "🚨 Escalations":
    st.title("🚨 Human Escalation Queue")

    esc_rate = get_escalation_resolution_rate()
    ea, eb, ec = st.columns(3)
    ea.metric("Total Cases",    esc_rate["total"])
    eb.metric("Open",           esc_rate["open"],     delta_color="inverse")
    ec.metric("Resolved",       esc_rate["resolved"], delta_color="normal")

    st.markdown("---")

    edf = get_open_escalations()
    if edf.empty:
        st.success("✅ No open escalation cases — queue is clear!")
    else:
        # Priority filter
        prios = ["All"] + sorted(edf["priority"].dropna().unique().tolist())
        sel_p = st.selectbox("Filter by priority", prios, key="esc_p")
        if sel_p != "All":
            edf = edf[edf["priority"] == sel_p]

        st.caption(f"{len(edf)} open case(s)")

        now = datetime.now()

        for _, row in edf.iterrows():
            prio_label = PRIORITY_LABEL.get(row["priority"], row["priority"])
            sla_str    = row.get("sla_deadline") or ""
            sla_status = ""
            if sla_str:
                try:
                    sla_dt = datetime.fromisoformat(sla_str)
                    if now > sla_dt:
                        sla_status = "🔴 **SLA BREACHED**"
                    else:
                        mins_left = int((sla_dt - now).total_seconds() / 60)
                        if mins_left < 60:
                            sla_status = f"⚠️ {mins_left}m remaining"
                        else:
                            sla_status = f"🟢 {mins_left//60}h {mins_left%60}m remaining"
                except Exception:
                    pass

            with st.expander(
                f"{prio_label} | **{row['customer_name'] or row['policy_number']}** | "
                f"{row['reason']} | Assigned: {row['agent_name'] or 'Unassigned'} | {sla_status}",
                expanded=(row["priority"] == "p1_urgent"),
            ):
                c1, c2 = st.columns(2)
                c1.markdown(f"**Case ID:** `{row['case_id']}`")
                c1.markdown(f"**Policy:** `{row['policy_number']}`")
                c1.markdown(f"**Reason:** {row['reason']}")
                c2.markdown(f"**Agent:** {row['agent_name'] or '—'} (`{row['assigned_to'] or 'unassigned'}`)")
                c2.markdown(f"**Created:** {row['created_at']}")
                c2.markdown(f"**SLA Deadline:** {sla_str}")
                if row.get("briefing_note"):
                    st.info(f"📋 {row['briefing_note']}")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 6 — Renewals Due
# ─────────────────────────────────────────────────────────────────────────────

elif page == "📅 Renewals Due":
    st.title("📅 Policies Due for Renewal")

    days = st.slider("Show policies due within next N days", 7, 90, 30, 7)
    rdf = get_policies_due(days)

    st.caption(f"{len(rdf)} policies due within {days} days")

    if not rdf.empty:
        # Summary bar — days bucket
        rdf["days_bucket"] = pd.cut(
            rdf["days_to_due"],
            bins=[-1, 7, 14, 21, 30, 60, 90],
            labels=["0-7d","8-14d","15-21d","22-30d","31-60d","61-90d"],
        )
        bucket_df = rdf.groupby("days_bucket", observed=True)["policy_number"].count().reset_index()
        bucket_df.columns = ["bucket", "count"]

        c1, c2 = st.columns([1, 2])
        with c1:
            fig = px.bar(
                bucket_df, x="bucket", y="count",
                color="count",
                color_continuous_scale="Reds_r",
                labels={"bucket": "Due window", "count": "Policies"},
            )
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#ccd6f6",
                margin=dict(l=10, r=10, t=10, b=10),
                height=240,
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig, use_container_width=True)

        with c2:
            channel_df = rdf.groupby("preferred_channel")["policy_number"].count().reset_index()
            channel_df.columns = ["channel", "count"]
            fig2 = px.pie(
                channel_df, names="channel", values="count",
                hole=0.5,
                color_discrete_sequence=["#25d366","#0068c9","#ff8c00"],
            )
            fig2.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                font_color="#ccd6f6",
                margin=dict(l=10, r=10, t=10, b=10),
                height=240,
                legend=dict(orientation="h", y=-0.1),
            )
            st.plotly_chart(fig2, use_container_width=True)

        # Table
        def _days_color(val: float) -> str:
            if pd.isna(val):
                return ""
            if val <= 7:
                return "color: #ff4b4b; font-weight: 700"
            if val <= 14:
                return "color: #ff8c00; font-weight: 600"
            return "color: #21c354"

        display_cols = [
            "policy_number","customer_name","product_name",
            "annual_premium","renewal_due_date","days_to_due",
            "preferred_channel","preferred_language","status",
        ]
        st.dataframe(
            rdf[display_cols].style.map(_days_color, subset=["days_to_due"]),
            use_container_width=True, height=420,
        )

        total_premium = rdf["annual_premium"].sum()
        st.metric("Total Premium at Risk", f"₹{total_premium:,.0f}")

    else:
        st.success(f"✅ No policies due within {days} days.")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 7 — Settings
# ─────────────────────────────────────────────────────────────────────────────

elif page == "⚙️  Settings":
    st.title("⚙️  Settings & Configuration")

    env_path = ROOT / ".env"
    if env_path.exists():
        with open(env_path) as f:
            lines = f.readlines()

        st.subheader("Environment Variables (.env)")
        st.caption("API keys are masked for security.")

        rows = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                # Mask keys that look like secrets
                sensitive = any(k in key.upper() for k in ["KEY","SECRET","TOKEN","SID","PASSWORD"])
                display_val = f"{val[:4]}{'*' * max(0, len(val)-4)}" if sensitive and len(val) > 4 else val
                rows.append({"Key": key.strip(), "Value": display_val})

        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, height=400)
    else:
        # Running on Streamlit Cloud — show active env vars instead
        st.subheader("Active Environment Variables")
        st.caption("Running on Streamlit Cloud — .env not present. Showing active configuration (keys masked).")
        import os as _os
        tracked_keys = [
            "GEMINI_API_KEY", "MOCK_DELIVERY", "GEMINI_MODEL_ORCHESTRATOR",
            "GEMINI_MODEL_EXECUTION", "GEMINI_MODEL_CRITIQUE", "GEMINI_MODEL_SAFETY",
            "GEMINI_MODEL_CLASSIFY", "GEMINI_MODEL_REPORT", "DB_PATH",
            "TWILIO_ACCOUNT_SID", "RAZORPAY_KEY_ID", "ELEVENLABS_API_KEY", "SARVAM_API_KEY",
        ]
        rows = []
        for key in tracked_keys:
            val = _os.environ.get(key, "")
            if not val:
                continue
            sensitive = any(k in key.upper() for k in ["KEY","SECRET","TOKEN","SID","PASSWORD"])
            display_val = f"{val[:4]}{'*' * max(0, len(val)-4)}" if sensitive and len(val) > 4 else val
            rows.append({"Key": key, "Value": display_val})
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, height=400)
        else:
            st.warning("No environment variables found. Add secrets in Streamlit Cloud → App Settings → Secrets.")

    st.divider()
    st.subheader("Agent Model Config")
    from core.config import settings as cfg
    model_data = [
        {"Role": "Orchestrator",  "Model": cfg.model_orchestrator},
        {"Role": "Execution",     "Model": cfg.model_execution},
        {"Role": "Critique",      "Model": cfg.model_critique},
        {"Role": "Safety",        "Model": cfg.model_safety},
        {"Role": "Classify",      "Model": cfg.model_classify},
        {"Role": "Report",        "Model": cfg.model_report},
    ]
    st.dataframe(pd.DataFrame(model_data), use_container_width=True, height=260)

    st.divider()
    st.subheader("Database Info")
    from dashboard.data_service import DB_PATH
    st.code(DB_PATH, language="text")
    db_size = Path(DB_PATH).stat().st_size if Path(DB_PATH).exists() else 0
    st.caption(f"DB size: {db_size / 1024:.1f} KB")
