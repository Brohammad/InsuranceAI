"""tests/test_human_queue.py — 20-specialist queue routing tests."""
from __future__ import annotations
import pytest
from agents.layer5_human.queue_manager import (
    MOCK_AGENTS, REASON_SKILL_MAP, SPECIALIST_TEAMS,
    _assign_agent, EscalationPriority,
)

def _reset():
    for a in MOCK_AGENTS:
        a["load"] = 0
        a["available"] = True

def test_twenty_specialists():
    assert len(MOCK_AGENTS) == 20

def test_all_agents_have_required_keys():
    for a in MOCK_AGENTS:
        for k in ("id","name","team","skills","languages","available","load","max_load","seniority"):
            assert k in a

def test_unique_agent_ids():
    ids = [a["id"] for a in MOCK_AGENTS]
    assert len(ids) == len(set(ids))

def test_six_teams():
    assert {a["team"] for a in MOCK_AGENTS} == set(SPECIALIST_TEAMS.keys())

def test_skill_map_has_expected_reasons():
    for r in ("distress","mis_selling","bereavement","complaint","requested_human"):
        assert r in REASON_SKILL_MAP

def test_assign_distress_gets_wellness_agent():
    _reset()
    agent_id, _ = _assign_agent(EscalationPriority.P2_HIGH.value, "distress", "en")
    assert agent_id is not None
    agent = next(a for a in MOCK_AGENTS if a["id"] == agent_id)
    assert "distress" in agent["skills"]

def test_assign_payment_query_gets_tech_agent():
    _reset()
    agent_id, _ = _assign_agent(EscalationPriority.P3_NORMAL.value, "payment_failure", "en")
    agent = next(a for a in MOCK_AGENTS if a["id"] == agent_id)
    assert "payment_query" in agent["skills"]

def test_assign_p1_prefers_senior():
    _reset()
    agent_id, _ = _assign_agent(EscalationPriority.P1_URGENT.value, "distress", "en")
    agent = next(a for a in MOCK_AGENTS if a["id"] == agent_id)
    assert agent["seniority"] in ("senior", "manager")

def test_assign_language_preference():
    _reset()
    agent_id, _ = _assign_agent(EscalationPriority.P3_NORMAL.value, "requested_human", "ta")
    agent = next(a for a in MOCK_AGENTS if a["id"] == agent_id)
    assert "ta" in agent["languages"]

def test_assign_returns_none_when_all_full():
    for a in MOCK_AGENTS:
        a["load"] = a["max_load"]
        a["available"] = True
    agent_id, _ = _assign_agent(EscalationPriority.P3_NORMAL.value, "requested_human", "en")
    assert agent_id is None
    _reset()

def test_assign_increments_load():
    _reset()
    agent_id, _ = _assign_agent(EscalationPriority.P3_NORMAL.value, "requested_human", "en")
    agent = next(a for a in MOCK_AGENTS if a["id"] == agent_id)
    assert agent["load"] == 1
