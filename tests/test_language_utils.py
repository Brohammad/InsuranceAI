"""
tests/test_language_utils.py
────────────────────────────
Tests for multi-language support:
  - language_utils.py — all 9 languages, all 3 channels
  - Smoke-import all 3 execution agents to confirm no import errors
  - WhatsApp/Email/Voice mock messages return native-language strings
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import date


# ── Helper data ────────────────────────────────────────────────────────────────

ALL_LANGUAGES = [
    "english", "hindi", "marathi", "bengali",
    "tamil", "telugu", "kannada", "malayalam", "gujarati",
]

# Native greeting keywords expected per language
# Native words that appear in the greeting/salutation per language
# WhatsApp uses "प्रिय" style greeting (Dear), Voice uses the spoken opening
NATIVE_WHATSAPP_GREETING = {
    "hindi":     "प्रिय",
    "marathi":   "प्रिय",
    "bengali":   "প্রিয়",
    "tamil":     "அன்புள்ள",
    "telugu":    "ప్రియమైన",
    "kannada":   "ಆತ್ಮೀಯ",
    "malayalam": "പ്രിയ",
    "gujarati":  "પ્રિય",
}

NATIVE_GREETINGS = {
    "hindi":     "नमस्ते",
    "marathi":   "नमस्कार",
    "bengali":   "নমস্কার",
    "tamil":     "வணக்கம்",
    "telugu":    "నమస్కారం",
    "kannada":   "ನಮಸ್ಕಾರ",
    "malayalam": "നമസ്കാരം",
    "gujarati":  "નમસ્તે",
}

MOCK_PARAMS = dict(
    channel   = "whatsapp",
    language  = "hindi",
    name      = "Rajesh",
    product   = "Term Life",
    policy_no = "POL-001",
    due_date  = "2025-12-01",
    premium   = "12,500",
)


# ── Tests: language_utils.get_language_config ──────────────────────────────────

def test_get_language_config_all_languages():
    from agents.layer2_execution.language_utils import get_language_config, LANGUAGE_CONFIG
    for lang in ALL_LANGUAGES:
        cfg = get_language_config(lang)
        assert "greeting"    in cfg, f"Missing 'greeting' for {lang}"
        assert "sign_off"    in cfg, f"Missing 'sign_off' for {lang}"
        assert "renew_cta"   in cfg, f"Missing 'renew_cta' for {lang}"
        assert "script_open" in cfg, f"Missing 'script_open' for {lang}"
        assert "script"      in cfg, f"Missing 'script' for {lang}"
    print(f"✅ get_language_config: all {len(ALL_LANGUAGES)} languages have required keys")


def test_get_language_config_fallback():
    from agents.layer2_execution.language_utils import get_language_config
    cfg = get_language_config("odia")   # unsupported → fallback to english
    assert cfg["native_name"] == "English"
    print("✅ get_language_config: unknown language falls back to English")


# ── Tests: build_language_instruction ─────────────────────────────────────────

def test_build_language_instruction_english():
    from agents.layer2_execution.language_utils import build_language_instruction
    instr = build_language_instruction("english", "Amit")
    assert "English" in instr
    assert "Amit" in instr
    print(f"✅ build_language_instruction English: {instr[:60]}")


def test_build_language_instruction_hindi():
    from agents.layer2_execution.language_utils import build_language_instruction
    instr = build_language_instruction("hindi", "Rajesh")
    assert "CRITICAL LANGUAGE INSTRUCTION" in instr
    assert "हिन्दी" in instr or "Hindi" in instr
    assert "Rajesh" in instr
    assert "नमस्ते" in instr or "प्रिय" in instr
    print(f"✅ build_language_instruction Hindi:\n  {instr[:120]}")


def test_build_language_instruction_all_non_english():
    from agents.layer2_execution.language_utils import build_language_instruction
    for lang in ALL_LANGUAGES:
        if lang == "english":
            continue
        instr = build_language_instruction(lang, "Test")
        assert "CRITICAL LANGUAGE INSTRUCTION" in instr, f"No critical block for {lang}"
        assert len(instr) > 50, f"Instruction too short for {lang}"
    print(f"✅ build_language_instruction: all {len(ALL_LANGUAGES)-1} non-English languages produce rich instructions")


# ── Tests: get_mock_message ────────────────────────────────────────────────────

def test_mock_whatsapp_all_languages():
    from agents.layer2_execution.language_utils import get_mock_message
    for lang in ALL_LANGUAGES:
        msg = get_mock_message(
            channel   = "whatsapp",
            language  = lang,
            name      = "Priya",
            product   = "Term Life",
            policy_no = "POL-001",
            due_date  = "2025-12-01",
            premium   = "10,000",
        )
        assert len(msg) > 20, f"WhatsApp mock too short for {lang}: {msg}"
        assert "POL-001" in msg, f"Policy number missing for {lang}"
    print(f"✅ get_mock_message(whatsapp): all {len(ALL_LANGUAGES)} languages produced messages")


def test_mock_voice_all_languages():
    from agents.layer2_execution.language_utils import get_mock_message
    for lang in ALL_LANGUAGES:
        msg = get_mock_message(
            channel   = "voice",
            language  = lang,
            name      = "Rajesh",
            product   = "Term Life",
            policy_no = "POL-002",
            due_date  = "2025-11-15",
            premium   = "15,000",
        )
        assert len(msg) > 20, f"Voice mock too short for {lang}: {msg}"
    print(f"✅ get_mock_message(voice): all {len(ALL_LANGUAGES)} languages produced scripts")


def test_mock_email_subject_all_languages():
    from agents.layer2_execution.language_utils import get_mock_message
    for lang in ALL_LANGUAGES:
        subj = get_mock_message(
            channel   = "email",
            language  = lang,
            name      = "Anita",
            product   = "Endowment",
            policy_no = "POL-003",
            due_date  = "2025-10-01",
            premium   = "8,000",
            subject   = True,
        )
        assert len(subj) > 5, f"Email subject too short for {lang}: {subj}"
        assert "POL-003" in subj, f"Policy number missing in subject for {lang}"
    print(f"✅ get_mock_message(email subject): all {len(ALL_LANGUAGES)} languages")


def test_native_greeting_in_voice_mock():
    from agents.layer2_execution.language_utils import get_mock_message
    for lang, greeting in NATIVE_GREETINGS.items():
        msg = get_mock_message(
            channel   = "voice",
            language  = lang,
            name      = "Test",
            product   = "Term",
            policy_no = "POL-XXX",
            due_date  = "2025-12-31",
            premium   = "5,000",
        )
        assert greeting in msg, f"Native greeting '{greeting}' not found in {lang} voice script: {msg}"
    print("✅ Native greetings verified in voice mock scripts for all regional languages")


# ── Tests: agent import smoke-test ────────────────────────────────────────────

def test_whatsapp_agent_import():
    from agents.layer2_execution.whatsapp_agent import WhatsAppAgent
    agent = WhatsAppAgent()
    assert agent is not None
    print("✅ WhatsAppAgent imports and initialises (language_utils wired)")


def test_email_agent_import():
    from agents.layer2_execution.email_agent import EmailAgent
    agent = EmailAgent()
    assert agent is not None
    print("✅ EmailAgent imports and initialises (language_utils wired)")


def test_voice_agent_import():
    from agents.layer2_execution.voice_agent import VoiceAgent
    agent = VoiceAgent()
    assert agent is not None
    print("✅ VoiceAgent imports and initialises (language_utils wired)")


# ── Tests: agents produce language-native mock output ─────────────────────────

def _make_customer(lang: str):
    """Create a minimal Customer-like object."""
    from unittest.mock import MagicMock
    from core.models import Language
    c = MagicMock()
    c.customer_id          = "C-TEST"
    c.name                 = "Rajesh Kumar"
    c.preferred_language   = Language(lang)
    c.phone                = "9999999999"
    c.email                = "test@test.com"
    return c


def _make_policy():
    from unittest.mock import MagicMock
    from core.models import ProductType
    p = MagicMock()
    p.policy_number   = "POL-LANG-001"
    p.product_name    = "Term Life Plus"
    p.product_type    = ProductType.TERM
    p.annual_premium  = 12500
    p.sum_assured     = 1000000
    p.renewal_due_date = date(2025, 12, 15)
    return p


@pytest.mark.parametrize("lang", ALL_LANGUAGES)
def test_whatsapp_mock_output_per_language(lang):
    from agents.layer2_execution.whatsapp_agent import WhatsAppAgent
    agent    = WhatsAppAgent()
    customer = _make_customer(lang)
    policy   = _make_policy()
    msg = agent._generate_message(customer, policy, tone="warm", strategy="renewal_reminder", days=15)
    assert len(msg) > 10, f"WhatsApp message too short for {lang}"
    assert "POL-LANG-001" in msg, f"Policy number missing for {lang}"
    # WhatsApp uses formal "Dear" style greeting, not the vocal greeting
    if lang in NATIVE_WHATSAPP_GREETING:
        assert NATIVE_WHATSAPP_GREETING[lang] in msg, f"No native greeting for {lang}: {msg}"


@pytest.mark.parametrize("lang", ALL_LANGUAGES)
def test_email_mock_output_per_language(lang):
    from agents.layer2_execution.email_agent import EmailAgent
    agent    = EmailAgent()
    customer = _make_customer(lang)
    policy   = _make_policy()
    result = agent._generate_email(customer, policy, tone="professional", strategy="renewal_reminder", days=10)
    assert "subject" in result
    assert "body"    in result
    assert len(result["body"]) > 10, f"Email body too short for {lang}"
    assert "POL-LANG-001" in result["body"] or "POL-LANG-001" in result["subject"]


@pytest.mark.parametrize("lang", ALL_LANGUAGES)
def test_voice_mock_output_per_language(lang):
    from agents.layer2_execution.voice_agent import VoiceAgent
    agent    = VoiceAgent()
    customer = _make_customer(lang)
    policy   = _make_policy()
    script = agent._generate_script(customer, policy, tone="empathetic", strategy="renewal_reminder", days=15)
    assert len(script) > 20, f"Voice script too short for {lang}"


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import pytest as pt
    pt.main([__file__, "-v", "--tb=short", "-p", "no:warnings"])
