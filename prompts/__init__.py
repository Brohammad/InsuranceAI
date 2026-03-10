"""
prompts/
────────
Central prompt library for all RenewAI agents.

All LLM prompt templates live here — one sub-module per layer.
Agents import their prompts from this package; no prompt text lives
inside the agent files themselves.

Usage::

    from prompts.layer1 import SEGMENTATION_PROMPT, PROPENSITY_PROMPT
    from prompts.layer2 import WA_PROMPT, EMAIL_PROMPT
    from prompts.layer3 import CRITIQUE_PROMPT, COMPLIANCE_PROMPT
    ...
"""

from prompts.layer1 import (
    SEGMENTATION_PROMPT,
    PROPENSITY_PROMPT,
    TIMING_PROMPT,
    CHANNEL_PROMPT,
)
from prompts.layer2 import (
    WA_PROMPT,
    EMAIL_PROMPT,
    VOICE_PROMPT,
    OBJECTION_PROMPT,
)
from prompts.layer3 import (
    CRITIQUE_PROMPT,
    COMPLIANCE_PROMPT,
    SAFETY_PROMPT,
    SENTIMENT_PROMPT,
)
from prompts.layer4 import ENRICH_PROMPT
from prompts.layer5 import BRIEF_PROMPT

__all__ = [
    # Layer 1 — Strategic
    "SEGMENTATION_PROMPT",
    "PROPENSITY_PROMPT",
    "TIMING_PROMPT",
    "CHANNEL_PROMPT",
    # Layer 2 — Execution
    "WA_PROMPT",
    "EMAIL_PROMPT",
    "VOICE_PROMPT",
    "OBJECTION_PROMPT",
    # Layer 3 — Quality
    "CRITIQUE_PROMPT",
    "COMPLIANCE_PROMPT",
    "SAFETY_PROMPT",
    "SENTIMENT_PROMPT",
    # Layer 4 — Learning
    "ENRICH_PROMPT",
    # Layer 5 — Human
    "BRIEF_PROMPT",
]
