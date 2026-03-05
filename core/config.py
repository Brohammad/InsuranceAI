"""
core/config.py
──────────────
Central configuration for Project RenewAI.
Loads from .env and exposes typed settings + Gemini client helpers.

Model strategy (from chatpwc.txt architecture):
  ORCHESTRATOR  → gemini-3.1-pro-preview   (highest reasoning, master planner)
  EXECUTION     → gemini-3-flash-preview   (fast, high-quality message generation)
  CRITIQUE      → gemini-2.5-pro           (strong reviewer, different from generator)
  SAFETY        → gemini-2.5-flash         (lowest latency — real-time distress detection)
  CLASSIFY      → gemini-2.5-flash         (segmentation, propensity, quality scoring)
  REPORT        → gemini-3-flash-preview   (summaries, dashboards)
"""

import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from google import genai


# ── Resolve project root ──────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent


# ── Streamlit Cloud: inject st.secrets into os.environ before Settings loads ──
def _inject_streamlit_secrets() -> None:
    """
    When running on Streamlit Community Cloud, secrets defined in the
    App Settings → Secrets UI are available via st.secrets.
    Inject them into os.environ so pydantic-settings picks them up.
    This is a no-op locally (st.secrets will be empty or unavailable).
    """
    try:
        import streamlit as st  # noqa: PLC0415
        for key, value in st.secrets.items():
            if isinstance(value, str) and key not in os.environ:
                os.environ[key] = value
    except Exception:
        pass  # Not running under Streamlit, or no secrets configured


_inject_streamlit_secrets()


class Settings(BaseSettings):
    """All configuration values, loaded from .env"""

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Gemini API key ─────────────────────────────────────────────────────
    gemini_api_key: str = Field(..., alias="GEMINI_API_KEY")

    # ── Model per agent role ───────────────────────────────────────────────
    model_orchestrator: str = Field("gemini-3.1-pro-preview", alias="GEMINI_MODEL_ORCHESTRATOR")
    model_execution:    str = Field("gemini-3-flash-preview",  alias="GEMINI_MODEL_EXECUTION")
    model_critique:     str = Field("gemini-2.5-pro",          alias="GEMINI_MODEL_CRITIQUE")
    model_safety:       str = Field("gemini-2.5-flash",        alias="GEMINI_MODEL_SAFETY")
    model_classify:     str = Field("gemini-2.5-flash",        alias="GEMINI_MODEL_CLASSIFY")
    model_report:       str = Field("gemini-3-flash-preview",  alias="GEMINI_MODEL_REPORT")

    # ── Database ───────────────────────────────────────────────────────────
    db_path:     str = Field("data/renewai.db", alias="DB_PATH")
    chroma_path: str = Field("memory/chromadb", alias="CHROMA_PATH")

    # ── Email (MailHog local SMTP) ─────────────────────────────────────────
    smtp_host:  str = Field("localhost",           alias="SMTP_HOST")
    smtp_port:  int = Field(1025,                  alias="SMTP_PORT")
    email_from: str = Field("renewai@suraksha.in", alias="EMAIL_FROM")

    # ── WhatsApp (Twilio Sandbox) ──────────────────────────────────────────
    twilio_account_sid:   str = Field("", alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token:    str = Field("", alias="TWILIO_AUTH_TOKEN")
    twilio_whatsapp_from: str = Field("whatsapp:+14155238886", alias="TWILIO_WHATSAPP_FROM")

    # ── Payment Gateway (Razorpay) ─────────────────────────────────────────
    razorpay_key_id:      str = Field("", alias="RAZORPAY_KEY_ID")
    razorpay_key_secret:  str = Field("", alias="RAZORPAY_KEY_SECRET")
    merchant_vpa:         str = Field("suraksha.life@razorpay", alias="MERCHANT_VPA")

    # ── ElevenLabs (Voice TTS — eleven_multilingual_v2 supports all 9 Indian languages) ──
    elevenlabs_api_key:           str = Field("", alias="ELEVENLABS_API_KEY")
    elevenlabs_voice_hindi:       str = Field("pNInz6obpgDQGcFmaJgB", alias="ELEVENLABS_VOICE_ID_HINDI")
    elevenlabs_voice_english:     str = Field("21m00Tcm4TlvDq8ikWAM", alias="ELEVENLABS_VOICE_ID_ENGLISH")
    elevenlabs_voice_tamil:       str = Field("AZnzlk1XvdvUeBnXmlld", alias="ELEVENLABS_VOICE_ID_TAMIL")
    elevenlabs_voice_telugu:      str = Field("AZnzlk1XvdvUeBnXmlld", alias="ELEVENLABS_VOICE_ID_TELUGU")
    elevenlabs_voice_kannada:     str = Field("AZnzlk1XvdvUeBnXmlld", alias="ELEVENLABS_VOICE_ID_KANNADA")
    elevenlabs_voice_malayalam:   str = Field("AZnzlk1XvdvUeBnXmlld", alias="ELEVENLABS_VOICE_ID_MALAYALAM")
    elevenlabs_voice_bengali:     str = Field("AZnzlk1XvdvUeBnXmlld", alias="ELEVENLABS_VOICE_ID_BENGALI")
    elevenlabs_voice_marathi:     str = Field("AZnzlk1XvdvUeBnXmlld", alias="ELEVENLABS_VOICE_ID_MARATHI")
    elevenlabs_voice_gujarati:    str = Field("AZnzlk1XvdvUeBnXmlld", alias="ELEVENLABS_VOICE_ID_GUJARATI")

    # ── Sarvam AI (Indian-language Voice TTS) ─────────────────────────────
    # Preferred over ElevenLabs for all Indian languages (hi/ta/te/kn/ml/bn/mr/gu)
    # Get API key at: https://dashboard.sarvam.ai
    sarvam_api_key:               str = Field("", alias="SARVAM_API_KEY")
    sarvam_tts_endpoint:          str = Field("https://api.sarvam.ai/text-to-speech", alias="SARVAM_TTS_ENDPOINT")
    # Sarvam speaker IDs per language (bulbul:v2 model supports all Indian languages)
    sarvam_speaker_hindi:         str = Field("meera",   alias="SARVAM_SPEAKER_HINDI")
    sarvam_speaker_tamil:         str = Field("meera",   alias="SARVAM_SPEAKER_TAMIL")
    sarvam_speaker_telugu:        str = Field("meera",   alias="SARVAM_SPEAKER_TELUGU")
    sarvam_speaker_kannada:       str = Field("meera",   alias="SARVAM_SPEAKER_KANNADA")
    sarvam_speaker_malayalam:     str = Field("meera",   alias="SARVAM_SPEAKER_MALAYALAM")
    sarvam_speaker_bengali:       str = Field("meera",   alias="SARVAM_SPEAKER_BENGALI")
    sarvam_speaker_marathi:       str = Field("meera",   alias="SARVAM_SPEAKER_MARATHI")
    sarvam_speaker_gujarati:      str = Field("meera",   alias="SARVAM_SPEAKER_GUJARATI")
    sarvam_speaker_english:       str = Field("meera",   alias="SARVAM_SPEAKER_ENGLISH")

    # ── Mock mode ──────────────────────────────────────────────────────────
    mock_delivery: bool = Field(True, alias="MOCK_DELIVERY")

    # ── App behaviour ──────────────────────────────────────────────────────
    log_level:              str = Field("INFO", alias="LOG_LEVEL")
    max_critique_retries:   int = Field(2,      alias="MAX_CRITIQUE_RETRIES")
    human_sla_urgent_hours: int = Field(2,      alias="HUMAN_ESCALATION_SLA_URGENT_HOURS")
    human_sla_high_hours:   int = Field(4,      alias="HUMAN_ESCALATION_SLA_HIGH_HOURS")
    human_sla_normal_hours: int = Field(24,     alias="HUMAN_ESCALATION_SLA_NORMAL_HOURS")

    # ── Derived absolute paths ─────────────────────────────────────────────
    @property
    def abs_db_path(self) -> Path:
        return ROOT_DIR / self.db_path

    @property
    def abs_chroma_path(self) -> Path:
        return ROOT_DIR / self.chroma_path


# ── Singleton ─────────────────────────────────────────────────────────────────
settings = Settings()


# ── Gemini client ─────────────────────────────────────────────────────────────
def get_gemini_client() -> genai.Client:
    """Return a configured google.genai Client (shared across agents)."""
    return genai.Client(api_key=settings.gemini_api_key)


def generate(prompt: str, model: str | None = None) -> str:
    """
    Convenience wrapper — send a single prompt, return text.
    Defaults to the execution model (fast, high-quality).
    """
    client = get_gemini_client()
    response = client.models.generate_content(
        model=model or settings.model_execution,
        contents=prompt,
    )
    return response.text


# ── Quick self-test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    from rich.console import Console
    from rich.table import Table

    console = Console()

    # Settings table
    t = Table(title="RenewAI — Configuration", show_header=True, header_style="bold magenta")
    t.add_column("Setting",    style="cyan",  min_width=22)
    t.add_column("Value",      style="green")
    key_set = bool(settings.gemini_api_key) and "your_gemini" not in settings.gemini_api_key
    t.add_row("API Key",       f"✅ {settings.gemini_api_key[:10]}..." if key_set else "❌ Not set")
    t.add_row("DB Path",       str(settings.abs_db_path))
    t.add_row("ChromaDB Path", str(settings.abs_chroma_path))
    t.add_row("SMTP",          f"{settings.smtp_host}:{settings.smtp_port}")
    t.add_row("Log Level",     settings.log_level)
    console.print(t)

    # Model assignment table
    m = Table(title="Model Assignments", show_header=True, header_style="bold cyan")
    m.add_column("Agent Role", style="yellow", min_width=16)
    m.add_column("Model",      style="green")
    m.add_column("Why",        style="white")
    m.add_row("Orchestrator",  settings.model_orchestrator, "Highest reasoning — master planner")
    m.add_row("Execution",     settings.model_execution,    "Fast + quality message generation")
    m.add_row("Critique",      settings.model_critique,     "Strong reviewer, diff from generator")
    m.add_row("Safety",        settings.model_safety,       "Lowest latency — real-time detection")
    m.add_row("Classify",      settings.model_classify,     "Segmentation, propensity, scoring")
    m.add_row("Report",        settings.model_report,       "Summaries & dashboard generation")
    console.print(m)

    if not key_set:
        console.print("\n[yellow]⚠  Set GEMINI_API_KEY in .env to test connections.[/yellow]")
    else:
        console.print("\n[bold yellow]Testing all models live...[/bold yellow]")
        test_models = {
            "Orchestrator": settings.model_orchestrator,
            "Execution":    settings.model_execution,
            "Critique":     settings.model_critique,
            "Safety":       settings.model_safety,
        }
        client = get_gemini_client()
        results = Table(title="Live Model Tests", show_header=True)
        results.add_column("Role",     style="cyan")
        results.add_column("Model",    style="yellow")
        results.add_column("Status",   style="green")
        results.add_column("Response", style="white", max_width=45)
        for role, model_id in test_models.items():
            try:
                resp = client.models.generate_content(
                    model=model_id,
                    contents=f"Reply with exactly: '{role} ready'",
                )
                results.add_row(role, model_id, "✅ OK", resp.text.strip()[:60])
            except Exception as e:
                results.add_row(role, model_id, "❌ FAIL", str(e)[:80])
        console.print(results)
