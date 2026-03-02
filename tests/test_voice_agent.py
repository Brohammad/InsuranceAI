"""
tests/test_voice_agent.py
──────────────────────────
Tests for the upgraded VoiceAgent:
  - ElevenLabs voice map (all 9 languages)
  - IRDAI call window compliance (is_within_call_window, get_next_call_window)
  - Intent detection (10 intents × English + Hindi keywords)
  - VoiceResult fields: intent, blocked_reason, audio_path
  - Full run() in mock mode for all 9 languages
  - Compliance block in non-mock mode outside call window
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import date
from unittest.mock import MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_customer(lang: str = "english"):
    from core.models import Language
    c = MagicMock()
    c.customer_id        = "C-VOICE-TEST"
    c.name               = "Priya Sharma"
    c.preferred_language = Language(lang)
    c.phone              = "9876543210"
    return c


def _make_policy():
    from core.models import ProductType
    p = MagicMock()
    p.policy_number    = "POL-VOICE-001"
    p.product_name     = "Term Life Plus"
    p.product_type     = ProductType.TERM
    p.annual_premium   = 18500
    p.sum_assured      = 2000000
    p.renewal_due_date = date(2025, 12, 31)
    return p


ALL_LANGS = [
    "english", "hindi", "marathi", "bengali",
    "tamil", "telugu", "kannada", "malayalam", "gujarati",
]


# ── Call window tests ─────────────────────────────────────────────────────────

def test_call_window_at_10am_ist():
    from datetime import datetime, timezone, timedelta
    from agents.layer2_execution.voice_agent import CALL_WINDOW_START, CALL_WINDOW_END, IST
    # 10:00 AM IST → inside window
    ist_10am = datetime(2025, 12, 1, 10, 0, 0, tzinfo=IST)
    assert CALL_WINDOW_START <= ist_10am.hour < CALL_WINDOW_END
    print("✅ 10 AM IST is inside call window")


def test_call_window_at_9pm_ist():
    from datetime import datetime, timezone, timedelta
    from agents.layer2_execution.voice_agent import CALL_WINDOW_START, CALL_WINDOW_END, IST
    # 9:00 PM IST → outside window
    ist_9pm = datetime(2025, 12, 1, 21, 0, 0, tzinfo=IST)
    assert not (CALL_WINDOW_START <= ist_9pm.hour < CALL_WINDOW_END)
    print("✅ 9 PM IST is outside call window")


def test_call_window_at_midnight_ist():
    from datetime import datetime
    from agents.layer2_execution.voice_agent import CALL_WINDOW_START, CALL_WINDOW_END, IST
    ist_midnight = datetime(2025, 12, 1, 0, 0, 0, tzinfo=IST)
    assert not (CALL_WINDOW_START <= ist_midnight.hour < CALL_WINDOW_END)
    print("✅ Midnight IST is outside call window")


def test_is_within_call_window_function_returns_bool():
    from agents.layer2_execution.voice_agent import is_within_call_window
    result = is_within_call_window()
    assert isinstance(result, bool)
    print(f"✅ is_within_call_window() returned {result} (bool)")


def test_get_next_call_window_format():
    from agents.layer2_execution.voice_agent import get_next_call_window
    msg = get_next_call_window()
    assert "IST" in msg
    assert "AM" in msg or "PM" in msg
    assert len(msg) > 10
    print(f"✅ get_next_call_window() = '{msg}'")


# ── ElevenLabs voice map ──────────────────────────────────────────────────────

def test_elevenlabs_voice_map_all_languages():
    from core.models import Language
    from agents.layer2_execution.voice_agent import _voice_id_for_language
    for lang in ALL_LANGS:
        voice_id = _voice_id_for_language(Language(lang))
        assert isinstance(voice_id, str)
        assert len(voice_id) > 5, f"Voice ID too short for {lang}: {voice_id}"
    print(f"✅ ElevenLabs voice map: all {len(ALL_LANGS)} languages have IDs")


def test_elevenlabs_voice_hindi_specific():
    from core.models import Language
    from agents.layer2_execution.voice_agent import _voice_id_for_language
    voice_id = _voice_id_for_language(Language.HINDI)
    assert voice_id == "pNInz6obpgDQGcFmaJgB"
    print(f"✅ ElevenLabs Hindi voice ID correct: {voice_id}")


def test_elevenlabs_voice_english_specific():
    from core.models import Language
    from agents.layer2_execution.voice_agent import _voice_id_for_language
    voice_id = _voice_id_for_language(Language.ENGLISH)
    assert voice_id == "21m00Tcm4TlvDq8ikWAM"
    print(f"✅ ElevenLabs English voice ID correct: {voice_id}")


# ── Intent detection ──────────────────────────────────────────────────────────

INTENT_CASES = [
    ("yes okay please send the payment link", "interested"),
    ("no I am not interested",                "not_interested"),
    ("call me back later I am busy",          "callback_requested"),
    ("how to pay via upi",                    "payment_query"),
    ("it is too expensive I cannot afford it","objection_price"),
    ("I am sick in hospital",                 "objection_health"),
    ("connect me to manager please",          "human_requested"),
    ("voicemail please leave a message",      "voicemail"),
    # Hindi
    ("nahi chahiye bandh karo",               "not_interested"),
    ("haan ji theek hai",                     "interested"),
    ("baad mein call karo main busy hoon",    "callback_requested"),
    ("mehenga hai afford nahi kar sakta",     "objection_price"),
    # Tamil
    ("சரி அனுப்புங்கள்",                     "interested"),
    ("வேண்டாம்",                             "not_interested"),
]


@pytest.mark.parametrize("text,expected_intent", INTENT_CASES)
def test_detect_intent(text, expected_intent):
    from agents.layer2_execution.voice_agent import detect_intent
    result = detect_intent(text)
    assert result == expected_intent, f"Expected '{expected_intent}' for '{text}', got '{result}'"


def test_detect_intent_unknown():
    from agents.layer2_execution.voice_agent import detect_intent
    result = detect_intent("random gibberish xyz")
    assert result == "unknown"
    print("✅ detect_intent returns 'unknown' for unrecognised text")


# ── VoiceAgent mock run ───────────────────────────────────────────────────────

@pytest.mark.parametrize("lang", ALL_LANGS)
def test_voice_agent_run_mock_all_languages(lang):
    from agents.layer2_execution.voice_agent import VoiceAgent
    from core.models import InteractionOutcome, Channel

    agent    = VoiceAgent()
    customer = _make_customer(lang)
    policy   = _make_policy()

    result, interaction = agent.run(
        customer   = customer,
        policy     = policy,
        journey_id = f"JRN-LANG-{lang.upper()}",
        step       = 1,
    )

    # VoiceResult assertions
    assert result.call_id.startswith("CALL")
    assert len(result.script) > 10,      f"Script too short for {lang}"
    assert result.audio_path is not None, f"No audio path for {lang}"
    assert result.mock is True
    assert isinstance(result.intent, str)
    assert result.blocked_reason == "",   f"Unexpected block for {lang}"
    assert isinstance(result.duration_sec, int)
    assert isinstance(result.sentiment, float)

    # Interaction assertions
    assert interaction.channel == Channel.VOICE
    assert interaction.policy_number == "POL-VOICE-001"
    assert interaction.customer_id   == "C-VOICE-TEST"

    print(f"  ✅ {lang}: intent={result.intent}, outcome={result.outcome.value}, duration={result.duration_sec}s")


def test_voice_agent_result_has_intent_field():
    from agents.layer2_execution.voice_agent import VoiceAgent
    agent    = VoiceAgent()
    customer = _make_customer("hindi")
    policy   = _make_policy()
    result, _ = agent.run(customer=customer, policy=policy, journey_id="JRN-INTENT-TEST")
    assert hasattr(result, "intent")
    assert result.intent in (
        "interested", "not_interested", "callback_requested",
        "payment_query", "objection_price", "objection_health",
        "human_requested", "voicemail", "unknown",
    )
    print(f"✅ VoiceResult.intent field present: {result.intent}")


def test_voice_agent_compliance_block_outside_window():
    """In real mode, calls outside 8AM-8PM must be blocked."""
    from agents.layer2_execution.voice_agent import VoiceAgent
    from core.models import InteractionOutcome

    agent      = VoiceAgent()
    agent.mock = False  # simulate real mode

    customer = _make_customer("english")
    policy   = _make_policy()

    # Patch is_within_call_window to return False (outside hours)
    with patch("agents.layer2_execution.voice_agent.is_within_call_window", return_value=False), \
         patch("agents.layer2_execution.voice_agent.get_next_call_window",   return_value="03 Mar 2026 at 08:00 AM IST"):
        result, interaction = agent.run(
            customer   = customer,
            policy     = policy,
            journey_id = "JRN-COMPLIANCE",
        )

    assert result.outcome        == InteractionOutcome.NO_RESPONSE
    assert result.intent         == "blocked"
    assert "8 AM" in result.blocked_reason or "8:00 AM" in result.blocked_reason or "blocked" in result.blocked_reason.lower()
    assert result.script         == ""
    assert result.audio_path     is None
    print(f"✅ Compliance block works: {result.blocked_reason[:80]}")


def test_voice_agent_script_contains_policy_number():
    from agents.layer2_execution.voice_agent import VoiceAgent
    agent    = VoiceAgent()
    customer = _make_customer("english")
    policy   = _make_policy()
    result, _ = agent.run(customer=customer, policy=policy, journey_id="JRN-SCRIPT-CHECK")
    assert "POL-VOICE-001" in result.script
    print(f"✅ Script contains policy number: {result.script[:80]}")


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import pytest as pt
    pt.main([__file__, "-v", "--tb=short", "-p", "no:warnings"])
