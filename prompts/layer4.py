"""
prompts/layer4.py
──────────────────
Layer 4 — Learning agent prompt templates.

Covers:
  • ReportAgent → ENRICH_PROMPT
"""

# ── Report enrichment ─────────────────────────────────────────────────────────

ENRICH_PROMPT = """\
You are the AI analytics engine for Suraksha Life Insurance's RenewAI system.
Based on the following renewal operations data, write a concise Executive Summary
(3-4 bullet points) and 5 specific actionable Recommendations for the operations team.

DATA:
{stats_json}

Focus on:
- Renewal rate improvement opportunities
- Segment-specific insights
- Quality and compliance gaps
- Safety escalation patterns
- A/B test learnings

Return plain text — bullets only, no markdown headers.
"""
