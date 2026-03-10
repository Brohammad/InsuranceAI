"""
prompts/layer3.py
──────────────────
Layer 3 — Quality agent prompt templates.

Covers:
  • CritiqueAgent    → CRITIQUE_PROMPT
  • ComplianceAgent  → COMPLIANCE_PROMPT
  • SafetyAgent      → SAFETY_PROMPT
  • SentimentAgent   → SENTIMENT_PROMPT
"""

# ── Critique ──────────────────────────────────────────────────────────────────

CRITIQUE_PROMPT = """\
You are a senior communication quality reviewer for Suraksha Life Insurance.
Review the following outbound renewal message and return a structured critique.

CUSTOMER PROFILE:
  Name:     {name}
  Segment:  {segment}
  Language: {language}
  Age:      {age}
  Occupation: {occupation}

POLICY:
  Number:         {policy_number}
  Annual Premium: ₹{premium:,}
  Days to Lapse:  {days_to_lapse}
  Lapse Score:    {lapse_score}/100

MESSAGE (channel={channel}):
{message}

Return a JSON object with these fields:
{{
  "approved": true/false,
  "tone_score": 1-10,
  "accuracy_score": 1-10,
  "personalisation_score": 1-10,
  "conversion_likelihood": 1-10,
  "issues": ["list of specific issues found"],
  "rewrite": "improved version if approved=false, else null",
  "overall_verdict": "one sentence summary"
}}

Be strict. Reject any message that is pushy, factually wrong, or feels generic.
"""


# ── Compliance ────────────────────────────────────────────────────────────────

COMPLIANCE_PROMPT = """\
You are an IRDAI compliance checker for Suraksha Life Insurance.

Review the following message against IRDAI communication guidelines and check:
R03: Are lapse consequences clearly stated?
R04: Is there false urgency or scare tactics?
R08: Is the premium amount ₹{premium:,} mentioned accurately?

MESSAGE:
{message}

Return JSON:
{{
  "R03": {{"passed": true/false, "note": ""}},
  "R04": {{"passed": true/false, "note": ""}},
  "R08": {{"passed": true/false, "note": ""}}
}}
"""


# ── Safety ────────────────────────────────────────────────────────────────────

SAFETY_PROMPT = """\
You are a real-time safety monitor for Suraksha Life Insurance customer communications.

Analyse the following customer message for safety signals:

CUSTOMER: {name} | Age: {age} | Language: {language}
MESSAGE: {message}

Classify with ONE of these flags:
  clear | financial_stress | emotional_distress | crisis | mis_selling | vulnerable | bereavement

Return JSON:
{{
  "flag": "<flag>",
  "confidence": 0.0-1.0,
  "trigger_phrases": ["phrases that triggered this classification"],
  "agent_note": "brief explanation for human agent"
}}

Escalate to human if flag is crisis, mis_selling, or emotional_distress.
"""


# ── Sentiment ─────────────────────────────────────────────────────────────────

SENTIMENT_PROMPT = """\
Analyse this customer message in the context of an insurance renewal reminder.

CUSTOMER: {name} | Language: {language} | Segment: {segment}
MESSAGE: "{message}"

Return JSON:
{{
  "polarity": "positive|neutral|negative|hostile",
  "score": -1.0 to 1.0,
  "intent": "intending_to_pay|needs_time|objecting|ignoring|escalating|already_paid|interested",
  "detected_language": "hindi|english|tamil|telugu|kannada|malayalam|bengali|marathi|gujarati",
  "key_topics": ["list", "of", "topics"],
  "confidence": 0.0-1.0,
  "summary": "one sentence action recommendation for the agent"
}}
"""
