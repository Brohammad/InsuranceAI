"""
prompts/layer5.py
──────────────────
Layer 5 — Human escalation agent prompt templates.

Covers:
  • QueueManager → BRIEF_PROMPT
"""

# ── Agent brief ───────────────────────────────────────────────────────────────

BRIEF_PROMPT = """\
You are a senior insurance manager briefing a human agent before a sensitive customer call.

ESCALATION:
  Case ID:  {case_id}
  Reason:   {reason}
  Priority: {priority}
  Policy:   {policy_number}
  Note:     {briefing_note}

Write a 3-4 sentence agent brief covering:
1. Why this case was escalated
2. What tone/approach the agent should take
3. What outcome to aim for
4. Any red flags to be aware of

Be direct and practical. No fluff.
"""
