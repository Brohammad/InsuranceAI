"""
agents/layer2_execution/voice_agent.py
───────────────────────────────────────
Voice Agent — Layer 2

Generates voice call scripts and (optionally) synthesises audio via ElevenLabs.

MOCK MODE (settings.mock_delivery = True):
  - Uses canned scripts from mock_utils (no LLM)
  - Skips ElevenLabs API call — returns a fake audio file path
  - Returns a random realistic call outcome (answered/no-answer/voicemail)

REAL MODE (settings.mock_delivery = False):
  - Generates script via Gemini (model_execution)
  - Synthesises audio via ElevenLabs TTS
  - Saves MP3 to outputs/voice/<journey_id>/<step>.mp3
  - In production this would be streamed to a telephony platform
    (Exotel, Ozonetel, etc.) for actual outbound dialling

ElevenLabs voice IDs per language are configured in .env.
Default voices are approximate — real deployment would use
fine-tuned Indian-language voices.
"""

from __future__ import annotations

import uuid
import os
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path

from loguru import logger

from core.config import settings, get_gemini_client
from core.models import Channel, Customer, Interaction, InteractionOutcome, Language, Policy
from agents.layer2_execution.mock_utils import (
    mock_delivery_id, mock_outcome, mock_sentiment, mock_voice_script,
)
from agents.layer2_execution.language_utils import (
    build_language_instruction, get_mock_message, build_agent_context,
)


# ── Output ────────────────────────────────────────────────────────────────────

@dataclass
class VoiceResult:
    call_id:      str
    script:       str
    audio_path:   str | None        # None if not synthesised
    outcome:      InteractionOutcome
    sentiment:    float
    duration_sec: int               # mock: random realistic call duration
    called_at:    datetime
    mock:         bool = True


# ── Prompt ────────────────────────────────────────────────────────────────────

VOICE_PROMPT = """
You are a voice call script writer at Suraksha Life Insurance.

{language_instruction}

Write a natural outbound renewal call script in {language}.
The script should sound like a real person speaking — no formal stiffness.
Include:
  1. Greeting + identity (use native-language greeting)
  2. Purpose (renewal due in {due_days} days, ₹{premium:,} premium)
  3. Offer to send WhatsApp payment link
  4. Graceful close

{agent_context}

Keep it under 90 seconds of speech (~200 words).
Write ONLY the agent's lines, no stage directions.
"""


# ── ElevenLabs voice map ──────────────────────────────────────────────────────

def _voice_id_for_language(language: Language) -> str:
    """Map Language enum → ElevenLabs voice ID from settings."""
    mapping = {
        Language.HINDI:     settings.elevenlabs_voice_hindi,
        Language.ENGLISH:   settings.elevenlabs_voice_english,
        Language.TAMIL:     settings.elevenlabs_voice_tamil,
        Language.TELUGU:    settings.elevenlabs_voice_telugu,
        Language.KANNADA:   settings.elevenlabs_voice_kannada,
        Language.MALAYALAM: settings.elevenlabs_voice_malayalam,
        Language.BENGALI:   settings.elevenlabs_voice_bengali,
        Language.MARATHI:   settings.elevenlabs_voice_marathi,
        Language.GUJARATI:  settings.elevenlabs_voice_gujarati,
    }
    return mapping.get(language, settings.elevenlabs_voice_english)


def _synthesise_elevenlabs(
    script: str,
    language: Language,
    output_path: Path,
) -> bool:
    """
    Call ElevenLabs TTS API and save MP3 to output_path.
    Returns True on success, False on failure.
    """
    try:
        import requests
        voice_id = _voice_id_for_language(language)
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key":   settings.elevenlabs_api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": script,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability":        0.5,
                "similarity_boost": 0.8,
                "style":            0.2,
                "use_speaker_boost": True,
            },
        }
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)
        logger.info(f"ElevenLabs audio saved → {output_path}")
        return True
    except Exception as e:
        logger.error(f"ElevenLabs TTS failed: {e}")
        return False


# ── Agent ─────────────────────────────────────────────────────────────────────

class VoiceAgent:
    """Generates voice call scripts and synthesises audio via ElevenLabs."""

    def __init__(self):
        self.mock = settings.mock_delivery
        if not self.mock:
            self.client = get_gemini_client()
            self.model  = settings.model_execution
        logger.info(f"VoiceAgent ready | mock={self.mock} | elevenlabs={'yes' if settings.elevenlabs_api_key and not self.mock else 'stub'}")

    def _generate_script(
        self, customer: Customer, policy: Policy,
        tone: str, strategy: str, days: int,
    ) -> str:
        lang = customer.preferred_language.value
        if self.mock:
            return get_mock_message(
                channel   = "voice",
                language  = lang,
                name      = customer.name.split()[0],
                product   = policy.product_type.value if hasattr(policy, "product_type") else "Life",
                policy_no = policy.policy_number,
                due_date  = str(policy.renewal_due_date),
                premium   = f"{policy.annual_premium:,.0f}",
            )
        agent_ctx = build_agent_context(customer.customer_id, f"voice renewal {strategy}", channel="voice")
        prompt = VOICE_PROMPT.format(
            language_instruction = build_language_instruction(lang, customer.name.split()[0]),
            language     = lang,
            due_days     = days,
            premium      = policy.annual_premium,
            policy_number= policy.policy_number,
            tone         = tone,
            agent_context= agent_ctx,
        )
        resp = self.client.models.generate_content(model=self.model, contents=prompt)
        return resp.text.strip()

    def _synthesise(
        self, script: str, language: Language, journey_id: str, step: int
    ) -> str | None:
        """Synthesise audio. Returns local file path or None."""
        if self.mock:
            # Fake audio path — no actual file created in mock mode
            return f"outputs/voice/{journey_id}/step_{step}_mock.mp3"

        output_path = Path("outputs/voice") / journey_id / f"step_{step}.mp3"
        success = _synthesise_elevenlabs(script, language, output_path)
        return str(output_path) if success else None

    def run(
        self,
        customer:   Customer,
        policy:     Policy,
        journey_id: str,
        step:       int = 1,
        tone:       str = "empathetic",
        strategy:   str = "renewal_reminder",
    ) -> tuple[VoiceResult, Interaction]:
        import random
        days = max((policy.renewal_due_date - date.today()).days, 0)
        logger.debug(f"Voice → {customer.name} / {policy.policy_number}")

        script     = self._generate_script(customer, policy, tone, strategy, days)
        audio_path = self._synthesise(script, customer.preferred_language, journey_id, step)
        call_id    = mock_delivery_id("CALL")
        outcome    = mock_outcome(Channel.VOICE)
        sentiment  = mock_sentiment(outcome)
        duration   = random.randint(45, 180) if outcome == InteractionOutcome.RESPONDED else random.randint(0, 20)
        now        = datetime.now()

        result = VoiceResult(
            call_id      = call_id,
            script       = script,
            audio_path   = audio_path,
            outcome      = outcome,
            sentiment    = sentiment,
            duration_sec = duration,
            called_at    = now,
            mock         = self.mock,
        )

        interaction = Interaction(
            interaction_id  = f"INT-{uuid.uuid4().hex[:8].upper()}",
            journey_id      = journey_id,
            policy_number   = policy.policy_number,
            customer_id     = customer.customer_id,
            channel         = Channel.VOICE,
            direction       = "outbound",
            message_content = script[:500],
            language        = customer.preferred_language,
            sent_at         = now,
            outcome         = outcome,
            sentiment_score = sentiment,
        )

        logger.info(
            f"Voice call {call_id} → {customer.name} | outcome={outcome.value} "
            f"| duration={duration}s | audio={'saved' if audio_path else 'none'} | mock={self.mock}"
        )
        return result, interaction
