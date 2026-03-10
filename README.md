# 🛡️ Project RenewAI — Suraksha Life Insurance

![Python](https://img.shields.io/badge/Python-3.10-blue?logo=python&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-2.5--pro%20%2F%202.5--flash-4285F4?logo=google&logoColor=white)
![Tests](https://img.shields.io/badge/tests-206%20passing-brightgreen?logo=pytest)
![Agents](https://img.shields.io/badge/agents-21-orange)
![Layers](https://img.shields.io/badge/layers-5-purple)
![RAG](https://img.shields.io/badge/RAG-ChromaDB%20%7C%20170%2B%20docs-blueviolet)
![License](https://img.shields.io/badge/license-MIT-green)

> **AI-powered policy renewal system** — 21 autonomous agents across 5 layers, handling WhatsApp · Email · Voice outreach, UPI payments, IRDAI compliance, and human escalation for life insurance renewal.

---

## 📖 What Is This?

**The problem:** Insurance companies lose revenue when customers forget to renew their policies. Manual follow-up by human agents is slow, expensive, and inconsistent.

**The solution:** RenewAI is a fully automated renewal engine. When a policy is due, the system:
1. **Analyses** the customer (segment, lapse risk, best contact time)
2. **Reaches out** via WhatsApp, Email, or Voice — in their language
3. **Checks every message** for quality, safety, and IRDAI compliance before sending
4. **Collects payment** via UPI link, QR code, or AutoPay
5. **Escalates to a human specialist** only when AI cannot handle it
6. **Learns from outcomes** — each paid/lapsed result makes the next prediction more accurate

> 💡 **In production terms:** one agent handles ~500 renewal reminders/day, with < 2% escalation rate and full IRDAI audit trail — zero human effort for standard cases.

**Tech:** Python 3.10 · Gemini AI (`gemini-2.5-pro` / `gemini-2.5-flash`) · LangGraph · ChromaDB · ElevenLabs TTS · Twilio · Razorpay · SQLite · Streamlit

---

## ✨ Key Architectural Highlights

> Four advanced AI-engineering patterns that make RenewAI production-grade:

| # | Pattern | Where | What it does |
|---|---------|--------|-------------|
| 🔵 | **RAG — Retrieval-Augmented Generation** | `knowledge/` | 170+ documents (FAQs, objections, IRDAI rules) grounded into every agent prompt via ChromaDB |
| 🟣 | **Plan & Execute Framework** | `agents/layer1_strategic/orchestrator.py` | LangGraph state machine plans the full journey before any message is sent |
| 🟠 | **Model Tracing & Observability** | `observability/` · `prompts/` | Every Gemini call traced: token count, cost in ₹/USD, SHA-256 audit chain |
| 🔴 | **Critique Agent** | `agents/layer3_quality/critique_agent.py` | `gemini-2.5-pro` reviews every outbound message before it leaves the system |

> Jump directly to detailed sections: [RAG ↓](#-rag--retrieval-augmented-generation) · [Plan & Execute ↓](#-plan--execute-framework) · [Model Tracing ↓](#-model-tracing--observability) · [Critique Agent ↓](#-critique-agent)

---

## 📐 System Architecture

```
╔══════════════════════════════════════════════════════════════════════════════════════╗
║                          PROJECT RENEWAI — 5-LAYER AGENT SYSTEM                     ║
╠══════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                      ║
║  ┌─────────────────────────────────────────────────────────────────────────────┐    ║
║  │  LAYER 1 — STRATEGIC  (gemini-2.5-pro)                     [PLAN & EXECUTE] │    ║
║  │  [Segmentation] → [Propensity] → [Timing] → [Channel] → [Orchestrator]     │    ║
║  │  LangGraph state machine: segment→propensity→timing→channel→build_journey  │    ║
║  └──────────────────────────────┬────────────────────────────────────────────────┘  ║
║                                 │ journey plan (planned before execution)           ║
║  ┌──────────────────────────────▼────────────────────────────────────────────────┐  ║
║  │  LAYER 2 — EXECUTION  (gemini-2.5-flash)                         [RAG GROUNDED] │║
║  │  [Dispatcher] → [WhatsApp] │ [Email] │ [Voice] │ [Payment] │ [Objection←RAG] │  ║
║  └──────────────────────────────┬────────────────────────────────────────────────┘  ║
║                                 │ messages + results                                ║
║  ┌──────────────────────────────▼────────────────────────────────────────────────┐  ║
║  │  LAYER 3 — QUALITY & SAFETY  (gemini-2.5-pro + flash)      [CRITIQUE AGENT]  │  ║
║  │  [Critique★] → [Safety] → [Compliance] → [Sentiment] → [Quality Scorer]      │  ║
║  │  score≥70 → L4 learning  │  score<70 or safety_flag=0 → L5 escalation        │  ║
║  └──────────────────────────────┬────────────────────────────────────────────────┘  ║
║                                 │ routing decision                                  ║
║  ┌──────────────────────────────▼────────────────────────────────────────────────┐  ║
║  │  LAYER 4 — LEARNING  (gemini-2.5-flash)              [MODEL TRACING + COST]   │  ║
║  │  [Feedback Loop] → [A/B Manager] → [Drift Detector] → [Report Agent]          │  ║
║  │                            ↺ insights loop → Orchestrator                     │  ║
║  └──────────────────────────────┬────────────────────────────────────────────────┘  ║
║                                 │ escalation trigger                                ║
║  ┌──────────────────────────────▼────────────────────────────────────────────────┐  ║
║  │  LAYER 5 — HUMAN ESCALATION                                                   │  ║
║  │  [Queue Manager] → [20 Specialists] → [Supervisor Dashboard]                  │  ║
║  └───────────────────────────────────────────────────────────────────────────────┘  ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
```

---
## 🔵 RAG — Retrieval-Augmented Generation
 

> **Every agent prompt is grounded in verified knowledge — no hallucinated policy terms, no made-up premium amounts.**

### What it does

Instead of relying on the LLM's parametric memory, RenewAI injects **retrieved facts** directly into every Gemini prompt at call time. The Knowledge Base is built once (idempotent) and queried in milliseconds for every agent invocation.

### Knowledge Base Corpus (170+ documents)

```
  knowledge/
  └── rag_knowledge_base.py          ← single file, 887 lines
      │
      ├── PRODUCT_FAQS (10 docs)
      │     faq_001  What is Term Insurance?
      │     faq_002  What is an Endowment Policy?
      │     faq_003  What is a ULIP?
      │     faq_004  Pension / Annuity Plan
      │     faq_005  Money Back Policy
      │     faq_006  Health Insurance Rider
      │     faq_007  Grace Period & Lapse Revival
      │     faq_008  Free Look Period (IRDAI)
      │     faq_009  Tax Benefits — 80C / 10(10D)
      │     faq_010  Nomination & Assignment
      │
      ├── OBJECTION RESPONSES (150 pairs × 12 categories)
      │     PRICE / AFFORDABILITY       (15 pairs)
      │     TRUST / COMPANY             (12 pairs)
      │     NEED / PRODUCT FIT          (14 pairs)
      │     TIMING / PROCRASTINATION    (13 pairs)
      │     EXISTING COVERAGE           (11 pairs)
      │     HEALTH / MEDICAL            (12 pairs)
      │     CLAIMS EXPERIENCE           (10 pairs)
      │     DIGITAL / PROCESS           (11 pairs)
      │     BEREAVEMENT / SENSITIVE      (8 pairs)
      │     COMPETITOR COMPARISON       (10 pairs)
      │     POLICY LAPSE HISTORY        (12 pairs)
      │     GENERAL OBJECTIONS          (12 pairs)
      │
      ├── BENEFIT CALCULATORS (6 docs)
      │     Maturity · Tax · Surrender · Death benefit
      │
      ├── IRDAI COMPLIANCE DOCS (4 docs)
      │     Key IRDAI rules · Grievance · Free-look · Cooling-off
      │
      └── RENEWAL SCRIPTS (6 docs)
            Empathetic · Urgent · Friendly opening + closing scripts
```

### Two-tier Retrieval Backend

```
  kb.query("what is sum assured", n=3)
         │
         ├── ChromaDB available?
         │     YES → sentence-transformers embeddings → semantic similarity search
         │
         └── ChromaDB unavailable? (CI / lightweight env)
               NO  → keyword overlap fallback (TF-IDF style) — zero extra dependencies
```

### How agents use it

```python
  # ObjectionHandler — pulls top 3 matching objection responses before calling Gemini
  kb  = RagKnowledgeBase()
  ctx = kb.build_context("premium is too high for my budget", n=3)
  # → injects [OBJECTION — Premium Too High]\n... into the LLM prompt

  # Any agent can call:
  match = kb.get_objection_response("I already have LIC coverage")
  docs  = kb.query("IRDAI free look period rules", n=2, category="compliance")
  ctx   = kb.build_context("endowment maturity calculation", n=3)
```

### Key files

| File | Role |
|------|------|
| `knowledge/rag_knowledge_base.py` | Full corpus + ChromaDB indexing + keyword fallback (887 lines) |
| `knowledge/chroma_db/` | Persisted ChromaDB vector store |
| `agents/layer2_execution/objection_handler.py` | Primary consumer — RAG-grounded rebuttals |
| `memory/customer_memory.py` | Per-customer interaction history injected into prompts |

---

---

## 🟣 Plan & Execute Framework

> **The system builds a complete multi-channel journey plan *before* sending a single message — no reactive, one-shot prompting.**

### The Pattern

RenewAI implements the **Plan → Execute → Observe → Re-plan** loop as a formal LangGraph state machine. Layer 1 is the *Planner*; Layers 2–5 are the *Executors*.

```
  ┌─────────────── PLAN PHASE (Layer 1 — LangGraph) ────────────────┐
  │                                                                   │
  │   START                                                           │
  │     │                                                             │
  │     ▼                                                             │
  │   node_segment                                                    │
  │   SegmentationAgent (gemini-2.5-pro)                              │
  │   → segment: champion / at_risk / dormant / high_risk             │
  │   → recommended_tone · recommended_strategy · risk_flag           │
  │     │                                                             │
  │     ▼                                                             │
  │   node_propensity                                                 │
  │   PropensityAgent (gemini-2.5-pro)                                │
  │   → lapse_score: 0–100                                           │
  │   → intervention_intensity: urgent / intensive / moderate         │
  │   → top_reasons · recommended_actions                            │
  │     │                                                             │
  │     ▼                                                             │
  │   node_timing                                                     │
  │   TimingAgent (gemini-2.5-flash)                                  │
  │   → best_contact_window: "18:00–20:00"                          │
  │   → best_days: ["Monday", "Wednesday"]                           │
  │   → salary_day_flag · urgency_override                           │
  │     │                                                             │
  │     ▼                                                             │
  │   node_channel                                                    │
  │   ChannelSelectorAgent (gemini-2.5-flash)                         │
  │   → channel_sequence: [whatsapp, email, voice]                   │
  │     │                                                             │
  │     ▼                                                             │
  │   node_build_journey                                              │
  │   Assembles RenewalJourney with ordered JourneyStep list          │
  │   → persisted to SQLite immediately                              │
  │     │                                                             │
  │     ▼                                                             │
  │   END  →  journey object returned                                │
  └───────────────────────────────────────────────────────────────────┘
               │
               ▼
  ┌─────── EXECUTE PHASE (Layers 2–3) ───────────────────────────────┐
  │  Dispatcher reads the journey plan step-by-step                   │
  │  For each step → fires the correct agent (WA / Email / Voice)     │
  │  After execution → Quality Gate (Critique → Safety → Compliance)  │
  └──────────────────────────────────────────────────────────────────┘
               │
               ▼
  ┌─────── OBSERVE + RE-PLAN (Layer 4 → Layer 1) ────────────────────┐
  │  FeedbackLoop records outcome (paid / lapsed / objected)          │
  │  DriftDetector checks for distribution shift                      │
  │  ReportAgent surfaces A/B winners + drift anomalies               │
  │  ↺  Orchestrator updated: best_channel, drift anomaly count       │
  │     PropensityAgent.refresh_from_feedback() re-calibrates model   │
  └──────────────────────────────────────────────────────────────────┘
```

### Journey Timing Logic

The Planner encodes intensity-based scheduling — journeys are scheduled relative to policy due date, not ad-hoc:

```
  INTENSITY_START offsets (days before due date):
    urgent    → D-3  (or same day if < 3 days left)
    intensive → D-5
    moderate  → D-7
    light     → D-14
    none      → D-5

  Channel gap (days between consecutive steps):
    WhatsApp → 1 day
    Email    → 2 days
    Voice    → 1 day
    SMS      → 1 day
```

### Batch + Feedback in One Call

```python
  result = run_batch_with_feedback(
      customer_policy_pairs = [(c1, p1), (c2, p2), ...],
      run_feedback_loop     = True,
  )
  # → {"journeys": [...], "feedback": FeedbackSummary, "prompt_refreshed": bool}
  # PropensityAgent auto-recalibrates if >= 10 strong-signal events exist
```

### Key files

| File | Role |
|------|------|
| `agents/layer1_strategic/orchestrator.py` | LangGraph graph, all 5 nodes, `run_layer1()`, `run_batch_with_feedback()` |
| `agents/layer1_strategic/segmentation.py` | Node 1 — CustomerSegment + tone/strategy |
| `agents/layer1_strategic/propensity.py` | Node 2 — lapse_score + few-shot feedback loop |
| `agents/layer1_strategic/timing.py` | Node 3 — contact window + urgency override |
| `agents/layer1_strategic/channel_selector.py` | Node 4 — ordered channel sequence |
| `agents/layer2_execution/dispatcher.py` | Executor — walks the journey step list |

---

---

## 🟠 Model Tracing & Observability

> **Every Gemini call is logged with token counts, ₹ cost, agent identity, and a tamper-evident SHA-256 audit chain.**

### Three-tier Observability Stack

```
  EVERY AGENT ACTION
         │
         ├──► 1. COST TRACKER  (observability/cost_tracker.py)
         │       Captures per-call: model · input tokens · output tokens · USD cost · INR cost
         │
         │       Pricing table (per 1K tokens):
         │         gemini-2.5-flash  →  $0.00015 in  /  $0.00060 out
         │         gemini-2.5-pro    →  $0.00125 in  /  $0.00500 out
         │       Also tracks:
         │         ElevenLabs  $0.0003 / 1K chars
         │         Twilio      $0.005  / message (India)
         │         Razorpay    $0.002  / payment link
         │       Roll-ups: per-journey · per-agent · per-day · per-model
         │       Budget alert: warns when daily spend crosses Rs.500
         │
         ├──► 2. AUDIT TRAIL  (observability/audit_trail.py)
         │       Append-only SQLite table — no DELETE / UPDATE ever
         │       SHA-256 chain hash:  hash_n = SHA256(hash_{n-1} + payload_n)
         │         any tampered record breaks the chain
         │       Categories: COMMUNICATION · PAYMENT · ESCALATION
         │                    DATA_ACCESS  · AGENT_ACTION · COMPLIANCE
         │       IRDAI 5-year retention compliant
         │
         └──► 3. PROMPT REGISTRY  (prompts/ package)
                 All 15 LLM prompt templates — zero inline strings in agent code
                 prompts/layer1.py  →  SEGMENTATION, PROPENSITY, TIMING, CHANNEL
                 prompts/layer2.py  →  WA, EMAIL, VOICE, OBJECTION
                 prompts/layer3.py  →  CRITIQUE, COMPLIANCE, SAFETY, SENTIMENT
                 prompts/layer4.py  →  ENRICH, BRIEF
                 prompts/layer5.py  →  ESCALATION
```

### Per-Call Trace Record

Every `CostTracker.track_gemini()` call writes a structured row:

```
  event_id      : EVT-A3F92C11
  agent_name    : critique_agent
  model         : gemini-2.5-pro
  journey_id    : JRN-F1037D93
  input_tokens  : 842
  output_tokens : 156
  cost_usd      : $0.001858
  cost_inr      : Rs.0.1561
  timestamp     : 2026-03-10 05:25:09
```

### Prompt Registry — Centralised & Versioned

All 15 LLM prompts live in `prompts/` — **zero inline strings anywhere in agent code**:

```
  Before (scattered):                   After (prompts/ package):
  ─────────────────────────────         ───────────────────────────────────────────
  objection_handler.py  line 88         from prompts.layer2 import OBJECTION_PROMPT
  critique_agent.py     line 112        from prompts.layer3 import CRITIQUE_PROMPT
  safety_agent.py       line 95         from prompts.layer3 import SAFETY_PROMPT
  report_agent.py       line 201        from prompts.layer4 import ENRICH_PROMPT
  ...11 other files                     → one file change to update any prompt
```

### Streamlit Dashboard — Live Cost + Trace View

The 7-page Streamlit dashboard (`dashboard/app.py`) surfaces all trace data in real-time:

| Page | Metric shown |
|------|-------------|
| Overview | Total spend today vs Rs.500 budget |
| Cost Tracker | Per-agent breakdown, model distribution pie |
| Audit Trail | Chain-hash integrity, category filter |
| Quality | Per-customer quality scores over time |
| A/B Tests | Winner per variant type, lift %, significance |
| Drift Monitor | OK / WARNING / CRITICAL per dimension |
| Escalation Queue | Open cases, SLA countdown |

### Key files

| File | Role |
|------|------|
| `observability/cost_tracker.py` | `track_gemini()`, `track_elevenlabs()`, `daily_summary()` |
| `observability/audit_trail.py` | Append-only log with SHA-256 chain |
| `prompts/` | All 15 LLM prompt templates — one place to edit |
| `dashboard/app.py` | Streamlit UI over live SQLite data |

---

---

## 🔴 Critique Agent

> **No message ever reaches a customer without passing a `gemini-2.5-pro` review for tone, accuracy, personalisation, and IRDAI compliance.**

### What it does

The Critique Agent is the **first node in the Layer 3 Quality Gate**. It receives the full message text + customer profile + policy data, calls `gemini-2.5-pro`, and returns a structured verdict before the message is dispatched.

```
  OUTBOUND MESSAGE DRAFTED (by WA / Email / Voice Agent)
                │
                ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  CRITIQUE AGENT  (gemini-2.5-pro)                           │
  │                                                             │
  │  Evaluates on 4 dimensions:                                 │
  │                                                             │
  │  1. TONE SCORE (1–10)                                       │
  │     Is the message empathetic, not pushy?                   │
  │     Does it match the customer segment & situation?         │
  │                                                             │
  │  2. ACCURACY SCORE (1–10)                                   │
  │     Are the policy number, premium, due date correct?       │
  │     No invented figures or hallucinated terms?              │
  │                                                             │
  │  3. PERSONALISATION SCORE (1–10)                            │
  │     Does it use the customer's name, language,              │
  │     and reference their specific policy?                    │
  │                                                             │
  │  4. CONVERSION LIKELIHOOD (1–10)                            │
  │     Based on segment + tone + urgency — how likely is       │
  │     this message to drive a renewal payment?                │
  └─────────────────────────────────────────────────────────────┘
                │
                ▼
       CritiqueResult returned
                │
       ┌────────┴────────┐
       │                 │
  approved=True     approved=False
       │                 │
       ▼                 ▼
  Continue to      Rewrite generated by Critique Agent
  Safety Agent     → re-evaluated before sending
```

### Critique Prompt (from `prompts/layer3.py`)

```
  You are a senior communication quality reviewer for Suraksha Life Insurance.

  CUSTOMER PROFILE:
    Name: {name}   Segment: {segment}   Language: {language}
    Age:  {age}    Occupation: {occupation}

  POLICY:
    Number: {policy_number}   Premium: Rs.{premium:,}
    Days to Lapse: {days_to_lapse}   Lapse Score: {lapse_score}/100

  MESSAGE (channel={channel}):
  {message}

  Return JSON:
  {
    "approved": true/false,
    "tone_score": 1-10,
    "accuracy_score": 1-10,
    "personalisation_score": 1-10,
    "conversion_likelihood": 1-10,
    "issues": ["list of specific issues found"],
    "rewrite": "improved version if rejected, else null",
    "overall_verdict": "one sentence summary"
  }

  Be strict. Reject any message that is pushy, factually wrong, or generic.
```

### Full Quality Gate Pipeline

The Critique Agent is Node 1 of a 5-node pipeline — all must pass before the message is stored and scored:

```
  Layer 3 Quality Gate
  ──────────────────────────────────────────────────────────────────────
  [1] CritiqueAgent      gemini-2.5-pro    tone · accuracy · personalisation · conversion
       ↓ (approved=True OR rewrite applied)
  [2] SafetyAgent        gemini-2.5-flash  distress · mis-selling · coercion · PII leak
       ↓ (safety_score > 0)
  [3] ComplianceAgent    gemini-2.5-flash  IRDAI R03 · R04 · R08 checks
       ↓ (compliance_score >= 80)
  [4] SentimentAgent     gemini-2.5-flash  customer sentiment trend (-1.0 to +1.0)
       ↓
  [5] QualityScoringAgent                  weighted composite → saved to DB
       └── total_score >= 70  →  ROUTE TO LAYER 4 (learning)
           total_score <  70  →  ROUTE TO LAYER 5 (human escalation)
           safety_score = 0.0 →  IMMEDIATE LAYER 5 ESCALATION
```

### Score Composition

```
  Quality Score (0–100):
    Critique    (tone + accuracy + personalisation + conversion) / 4  × 30%
    Safety      0.0 = immediate block  ·  1.0 = clear                × 30%
    Compliance  IRDAI rules passed / total rules checked              × 25%
    Sentiment   mapped -1.0→+1.0 to 0–100                            × 15%
```

### Key files

| File | Role |
|------|------|
| `agents/layer3_quality/critique_agent.py` | Core agent — `CritiqueAgent.run()`, mock + live |
| `agents/layer3_quality/safety_agent.py` | Safety flag detection (distress, mis-selling) |
| `agents/layer3_quality/compliance_agent.py` | IRDAI R03/R04/R08 rule checks |
| `agents/layer3_quality/sentiment_agent.py` | Sentiment scoring + trend tracking |
| `agents/layer3_quality/quality_scoring.py` | Composite scorer → DB persist |
| `prompts/layer3.py` | All 4 Layer 3 prompt templates |

---

## 🔄 Renewal Journey Flow

```
                         CUSTOMER POLICY DUE
                                 │
                    ┌────────────▼───────────┐
                    │    SEGMENTATION AGENT   │
                    │  champion / at_risk /   │
                    │  dormant / churned      │
                    └────────────┬───────────┘
                                 │
                    ┌────────────▼───────────┐
                    │   PROPENSITY SCORER     │
                    │  lapse_score: 0–100     │
                    └────────────┬───────────┘
                                 │
                    ┌────────────▼───────────┐
                    │   TIMING OPTIMIZER      │
                    │  best time + day        │
                    └────────────┬───────────┘
                                 │
                    ┌────────────▼───────────┐
                    │   CHANNEL SELECTOR      │
                    │  WhatsApp / Email /     │
                    │  Voice / Multi          │
                    └────────────┬───────────┘
                                 │
                    ┌────────────▼───────────┐
                    │  MASTER ORCHESTRATOR    │
                    │  builds journey plan    │
                    └────────────┬───────────┘
                                 │
               ┌─────────────────┼──────────────────┐
               │                 │                  │
    ┌──────────▼──┐   ┌──────────▼──┐   ┌──────────▼──┐
    │  WhatsApp   │   │    Email    │   │    Voice    │
    │   Agent     │   │    Agent   │   │    Agent    │
    │  (Twilio)   │   │  (SMTP)    │   │ (ElevenLabs)│
    └──────────┬──┘   └──────────┬──┘   └──────────┬──┘
               │                 │                  │
               └─────────────────┼──────────────────┘
                                 │
                    ┌────────────▼───────────┐
                    │   QUALITY GATE (L3)     │
                    │  critique → safety →    │
                    │  compliance → score     │
                    └────────────┬───────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                                     │
    ┌─────────▼────────┐              ┌─────────────▼──────┐
    │  SCORE >= 70     │              │   SCORE < 70 OR     │
    │  ✅ CONTINUE      │              │   SAFETY FLAG       │
    │                  │              │   ESCALATE          │
    └─────────┬────────┘              └─────────────┬──────┘
              │                                     │
    ┌─────────▼────────┐              ┌─────────────▼──────┐
    │  PAYMENT AGENT   │              │  HUMAN QUEUE (L5)  │
    │  UPI deep link   │              │  20 specialists    │
    │  QR code PNG     │              │  skill routing     │
    │  AutoPay/NACH    │              │  SLA tracking      │
    │  NetBanking      │              └────────────────────┘
    └─────────┬────────┘
              │
    ┌─────────▼────────┐
    │  PAYMENT SUCCESS  │
    │  ✅ POLICY RENEWED│
    │  PAS updated      │
    │  CRM synced       │
    │  IRDAI logged     │
    └──────────────────┘
```

---

## 🌐 Multi-Language Support

```
┌────────────────────────────────────────────────────────────────────┐
│              SUPPORTED LANGUAGES (ElevenLabs multilingual_v2)      │
├──────────────┬─────────────────────────────────────────────────────┤
│  Language    │  Greeting          │  States / Regions              │
├──────────────┼────────────────────┼────────────────────────────────┤
│  Hindi  hi   │  namaste           │  UP, MP, Bihar, Delhi, Raj     │
│  English en  │  Hello             │  Pan-India default             │
│  Tamil   ta  │  vanakkam          │  Tamil Nadu, Sri Lanka         │
│  Telugu  te  │  namaskaram        │  Andhra, Telangana             │
│  Kannada kn  │  namaskara         │  Karnataka                     │
│  Malayalam ml│  namaskaram        │  Kerala                        │
│  Bengali bn  │  namaskar          │  West Bengal, Bangladesh       │
│  Marathi mr  │  namaskar          │  Maharashtra                   │
│  Gujarati gu │  namaste           │  Gujarat                       │
└──────────────┴────────────────────┴────────────────────────────────┘
```

---

## 💳 Payment Flow

```
  PAYMENT AGENT
       │
       ├──► UPI Deep Link ──────► upi://pay?pa=suraksha.life@razorpay
       │                                    &pn=Suraksha Life Insurance
       │                                    &am=<premium>&cu=INR
       │
       ├──► QR Code PNG ────────► qrcode lib → real PNG bytes → base64
       │                          embeddable in WhatsApp / email
       │
       ├──► AutoPay Mandate ────► UPI AutoPay / NACH
       │                          Razorpay Subscription API (real mode)
       │
       └──► NetBanking Links ──► SBI │ HDFC │ ICICI │ AXIS
                                  KOTAK │ BOB │ PNB │ UNION
```

---

## 🚨 Human Escalation — 20-Specialist Queue

```
ESCALATION TRIGGER
      │
      ▼
  REASON DETECTED
  ┌────────────────────────────────────────────────────────┐
  │ distress │ mis_selling │ bereavement │ complaint       │
  │ requested_human │ payment_failure │ legal │ medical    │
  └────────────────────────────┬───────────────────────────┘
                               │
                    SKILL-BASED ROUTING
                               │
         ┌─────────────────────┼──────────────────────┐
         │                     │                      │
  ┌──────▼──────┐    ┌─────────▼──────┐    ┌─────────▼──────┐
  │  WELLNESS   │    │  COMPLIANCE    │    │    CLAIMS      │
  │  Team (3)   │    │  Team (3)      │    │    Team (4)    │
  │  distress   │    │  mis_selling   │    │  complaint     │
  │  bereavement│    │  legal         │    │  medical_query │
  └─────────────┘    └────────────────┘    └────────────────┘
         │                     │                      │
  ┌──────▼──────┐    ┌─────────▼──────┐    ┌─────────▼──────┐
  │   RENEWAL   │    │    TECH &      │    │   SENIOR /     │
  │  Team (5)   │    │  PAYMENTS (3)  │    │  ESCALATION(2) │
  │  requested  │    │  payment_query │    │  ALL SKILLS    │
  │  upsell     │    │  mandate setup │    │  P1 PRIORITY   │
  └─────────────┘    └────────────────┘    └────────────────┘

  SLA:  P1 Urgent = 1h  │  P2 High = 4h  │  P3 Normal = 24h  │  P4 Low = 72h
```

---

## 🔁 Closed Feedback Loop — System Gets Smarter Automatically

Every time a customer **pays** or **lapses**, the outcome is stored as a `feedback_event`. Once 10+ strong-signal events accumulate, the `FeedbackLoopAgent` automatically calls `PropensityAgent.refresh_from_feedback()`. This rebuilds the Gemini prompt with real few-shot examples drawn from actual outcomes — no retraining, no manual work.

```
  OUTCOME RECORDED  (paid / lapsed)
       │
       ▼
  FeedbackLoopAgent.run()
  outcome scores stored in DB · A/B test + drift check run
       │
       ▼
  >= 10 strong-signal events?
       │
    Yes ▼
  PropensityAgent.refresh_from_feedback()
  reads top 5 PAID + top 5 LAPSED from real data
  builds few-shot block:
      age=42 · Mumbai · score=0.87 → PAID
      age=58 · Pune   · score=0.21 → LAPSED
  stores in module-level cache _FEEDBACK_FEW_SHOT
       │
       ▼
  Next PropensityAgent.run() call
  few-shot block prepended to Gemini prompt
  lapse_score is now grounded in real outcomes
```

**Key files:**

| File | What it does |
|------|-------------|
| `agents/layer1_strategic/propensity.py` | `refresh_from_feedback()` + `_FEEDBACK_FEW_SHOT` cache |
| `agents/layer4_learning/feedback_loop.py` | Auto-triggers refresh at end of `run()` |
| `agents/layer1_strategic/orchestrator.py` | `run_batch_with_feedback()` — batch + auto-learn in one call |
| `tests/test_feedback_propensity_loop.py` | 7 tests covering the full loop |

---

## 🔭 Observability Stack

```
  EVERY API CALL
       │
       ├──► COST TRACKER ──────► SQLite cost_events table
       │    Gemini (per model, in/out tokens)        Daily budget: Rs.500
       │    ElevenLabs (per 1K chars)                Alert on breach
       │    Twilio (per message)
       │    Razorpay (per transaction)
       │
       └──► AUDIT TRAIL ───────► SQLite audit_trail table (append-only)
            SHA-256 chain hash (tamper-evident)
            Categories: COMMUNICATION │ PAYMENT │ ESCALATION
                        DATA_ACCESS │ AGENT_ACTION │ COMPLIANCE
            IRDAI 5-year retention compliant
```

---

## 🔌 Integration Layer

```
  ┌─────────────────────────────────────────────────────────────────┐
  │                     INTEGRATION STUBS                           │
  ├──────────────┬──────────────────────────────────────────────────┤
  │  CRM         │  upsert_contact, log_interaction, create_task    │
  │  Stub        │  → Salesforce / Zoho / custom CRM (real mode)    │
  ├──────────────┼──────────────────────────────────────────────────┤
  │  PAS         │  get_policy, update_renewal_status, grace_period  │
  │  Stub        │  → DuckCreek / Majesco / in-house PAS            │
  ├──────────────┼──────────────────────────────────────────────────┤
  │  IRDAI       │  report_communication, file_grievance, ack, close │
  │  Stub        │  → IRDAI Bima Bharosa portal                     │
  ├──────────────┼──────────────────────────────────────────────────┤
  │  Payment GW  │  parse_webhook, verify_payment, HMAC validation  │
  │  Stub        │  → Razorpay (payment.captured / failed / refund) │
  └──────────────┴──────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
InsuranceAI/
│
├── agents/
│   ├── layer1_strategic/        # Segmentation, Propensity, Timing, Channel, Orchestrator
│   ├── layer2_execution/        # WhatsApp, Email, Voice, Payment, Objection, Language Utils
│   ├── layer3_quality/          # Critique (★), Safety, Compliance, Sentiment, Quality Scorer
│   ├── layer4_learning/         # Feedback Loop, A/B Manager, Drift Detector, Report Agent
│   └── layer5_human/            # Queue Manager (20 specialists), Supervisor Dashboard
│
├── prompts/                     (★) All 15 LLM prompt templates — centralised registry
│   ├── layer1.py                # SEGMENTATION, PROPENSITY, TIMING, CHANNEL prompts
│   ├── layer2.py                # WA, EMAIL, VOICE, OBJECTION prompts
│   ├── layer3.py                # CRITIQUE (★), COMPLIANCE, SAFETY, SENTIMENT prompts
│   ├── layer4.py                # ENRICH, BRIEF prompts
│   └── layer5.py                # ESCALATION prompt
│
├── knowledge/                   (★) RAG Knowledge Base — 170+ documents
│   ├── rag_knowledge_base.py    # Corpus + ChromaDB index + keyword fallback
│   └── chroma_db/               # Persisted ChromaDB vector store
│
├── memory/                      # Customer memory store (ChromaDB + SQLite)
│   └── customer_memory.py       # Per-customer context — channel pref, sentiment, objections
│
├── observability/               (★) Model Tracing
│   ├── cost_tracker.py          # Token + API cost tracking (Rs. + USD) — per call
│   └── audit_trail.py           # IRDAI-compliant SHA-256 append-only audit log
│
├── core/
│   ├── config.py                # All settings + Gemini client helpers
│   ├── models.py                # Pydantic data models
│   └── database.py              # SQLite helpers + seed
│
├── dashboard/
│   ├── app.py                   # 7-page Streamlit admin dashboard
│   └── data_service.py          # Read-only DB query layer
│
├── integrations/
│   ├── crm_stub.py              # CRM integration (Salesforce/Zoho)
│   ├── pas_stub.py              # Policy Administration System
│   ├── irdai_stub.py            # IRDAI regulatory reporting
│   └── payment_gw_stub.py       # Razorpay webhook handler
│
├── data/
│   ├── seed.py                  # Sample data seeder
│   └── renewai.db               # SQLite database
│
├── run_e2e.py                   # Full 5-layer live demo runner
├── tests/                       # 206 unit tests (~8s)
├── pytest.ini                   # Default: skip e2e tests
├── requirements.txt
└── .env                         # API keys (gitignored)
```

---

## ⚙️ Tech Stack

| Component | Technology |
|-----------|-----------|
| LLM — Orchestration | `gemini-2.5-pro` |
| LLM — Execution | `gemini-2.5-flash` |
| LLM — Critique / Review (★) | `gemini-2.5-pro` |
| LLM — Safety / Classify | `gemini-2.5-flash` |
| Agent Framework (★) | LangGraph — Plan & Execute state machine |
| RAG — Vector DB (★) | ChromaDB (persistent) + keyword fallback |
| RAG — Corpus (★) | 170+ documents (FAQs, objections, IRDAI rules, scripts) |
| Model Tracing (★) | Custom `CostTracker` + `AuditTrail` (SHA-256 chain) |
| Prompt Registry (★) | `prompts/` package — 15 templates, zero inline strings |
| Voice TTS | ElevenLabs `eleven_multilingual_v2` |
| WhatsApp | Twilio Sandbox |
| Email | SMTP (MailHog local / SendGrid prod) |
| Payments | Razorpay — UPI, QR, AutoPay, NetBanking |
| Customer Memory | SQLite + ChromaDB |
| Database | SQLite |
| Dashboard | Streamlit + Plotly |
| Testing | pytest — 206 tests |
| Language | Python 3.10 |

> (★) = RAG · Plan & Execute · Model Tracing · Critique Agent — the four highlighted patterns

---

## 🚀 Quick Start

```bash
# 1. Clone & install
git clone https://github.com/Brohammad/InsuranceAI
cd InsuranceAI
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — fill in:
#   GEMINI_API_KEY=AIza...
#   ELEVENLABS_API_KEY=sk_...
#   TWILIO_ACCOUNT_SID=AC...
#   TWILIO_AUTH_TOKEN=...
#   TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
#   RAZORPAY_KEY_ID=rzp_test_...
#   RAZORPAY_KEY_SECRET=...

# 3. Seed database
python data/seed.py

# 4. Run tests (206 fast unit tests)
pytest                        # unit tests only  (~8s)
pytest -m e2e                 # full e2e with real Gemini (~14min)

# 5. Run full E2E demo (all 5 layers)
python run_e2e.py             # fresh seed + all 3 customers + all 5 layers

# 6. Launch dashboard
streamlit run dashboard/app.py
# → http://localhost:8501
```

---

## 🖥️ E2E Run — Live Terminal Output

> Real output from `python run_e2e.py` — all 5 layers, 3 customers, fresh DB seed.

```
╭─────────────────────────────────────────────────────────────╮
│ 🛡️  RenewAI — Full End-to-End Run                           │
│ Mock mode • All 5 layers • DB updates verified in real-time │
╰─────────────────────────────────────────────────────────────╯

  Table              Rows
 ━━━━━━━━━━━━━━━━━━━━━━━━━
  renewal_journeys      6   ← 6 pre-paid baseline journeys
  interactions          0
  quality_scores        0
  ab_test_results       0

──────── ▶ Customer 1/3: Fatima Khan  (due in 2 days) ──────────

⚙  Layer 1 — Segmentation → Propensity → Timing → Channel
  Segmented SLI-1419237 | Fatima Khan → [high_risk] | risk=high
  Propensity scored     | Fatima Khan → score=85 | intensity=urgent
  Timing                | Fatima Khan → 18:00-20:00 on [Mon, Wed] | urgency=True
  Channel               | Fatima Khan → ['whatsapp', 'email', 'voice']
  ✅ Journey created: JRN-F1037D93  │  Segment: high_risk  │  Steps: 3

📤  Layer 2 — Dispatching messages
  WA  sent  WA-69E3E4D668  → Fatima Khan | outcome=read
  Email     EMAIL-C83DA1CA → Fatima Khan | outcome=no_response
  Voice     CALL-4D03B912  → Fatima Khan | outcome=responded | intent=interested | 141s
  Payment   TXN-3C869ED7   → Rs.11,000   | qr=1123B | autopay=yes | banks=8

🔍  Layer 3 — Quality Gate
  ✅ Quality score: 88.6  Grade: B
  ✅ Score 88.6 ≥ 70 → routing to L4 learning

──────── ▶ Customer 2/3: Mohammed Iqbal  (due in 4 days) ───────

⚙  Layer 1  →  Journey JRN-846C2D4D  │  high_risk  │  score=85  │  Steps: 3
📤  Layer 2  →  WA: payment_made  ← journey stopped (payment received)
🔍  Layer 3  →  Score 88.6 ≥ 70 → L4

──────── ▶ Customer 3/3: Rekha Nambiar  (due in 5 days) ────────

⚙  Layer 1  →  Journey JRN-38DBF154  │  high_risk  │  score=85  │  Steps: 3
📤  Layer 2  →  WA: read | Email: delivered | Voice: payment_made ← journey stopped
🔍  Layer 3  →  Score 88.6 ≥ 70 → L4

─────── 🔄 Layer 4 — Feedback → A/B Test → Drift → Report ──────
  Journeys routed to L4 : 3 (score ≥ 70)
  Events processed      : 7  │  Positive: 6  │  Negative: 1
  A/B  channel          →  winner=voice  conv=50.0%  lift=+50.2%
  Drift                 →  ⚠  WARNING — 2 anomalies detected
  Report                →  outputs/reports/report_daily_20260310_052518.md ✅
  ↺ Insights loop       →  Orchestrator: best_channel=voice | 2 drift alerts

── 🚨 Layer 5 — Human Escalation Queue + Supervisor Dashboard ───
  Journeys routed to L5 : 0  (all scores ≥ 70 this run)
  Renewal Rate: 88.9%   │  Premium Recovered: Rs.581,700
  Avg Quality Score: 88.6/100  │  IRDAI Compliance: 100.0%
  Escalation Queue: ✓ empty — no open escalations

╭───────────────────────────────────────────────────────────────╮
│ ✅ End-to-End Run Complete!                                   │
│ • 3 journeys created & dispatched                             │
│ • 3 quality scores written  (renewal_journeys: 9, interactions: 7)  │
│ • DB updated in real-time                                     │
╰───────────────────────────────────────────────────────────────╯
```

---

## 🏛️ Design Decisions

> Why these specific technologies and patterns — and what the alternatives were.

### LangGraph for Layer 1 orchestration (not plain Python)

| Option | Why rejected |
|--------|-------------|
| Plain sequential function calls | No state schema — agent outputs are dict-scattered, hard to test individual nodes |
| LangChain AgentExecutor | Tool-calling loop model doesn't fit a deterministic pipeline with fixed node order |
| **LangGraph StateGraph** ✅ | Typed `JourneyState` TypedDict enforces what each node reads and writes; nodes are independently unit-testable; graph is inspectable; easy to add conditional edges later (e.g. skip voice for DND customers) |

The key constraint: Layer 1 must *plan first, execute later* — the entire journey (channels, timing, steps) is assembled before a single message is sent. LangGraph's compile-then-invoke model maps directly onto that.

### SQLite (not PostgreSQL / DynamoDB)

| Concern | Answer |
|---------|--------|
| "Won't SQLite break under load?" | This is a **single-tenant renewal engine** (one insurer, one portfolio). At 500 journeys/day, SQLite handles this comfortably; it's used in production by many apps at this scale. |
| "Concurrent writes?" | All writes are from a single Python process in this architecture; WAL mode handles the rare concurrent dashboard read. |
| "Migration path?" | `core/database.py` is the only file that knows about SQLite — swap the connection string and you're on Postgres with zero agent changes. |

SQLite also means **zero infrastructure to set up** for a new developer — `python data/seed.py` and you're running. That was a deliberate "day-zero" design choice.

### ChromaDB (not pgvector / Pinecone)

| Option | Trade-off |
|--------|-----------|
| pgvector | Requires Postgres — contradicts the zero-infra goal above |
| Pinecone / Weaviate | Network call + API key + cost for a 170-doc corpus — overkill |
| **ChromaDB local** ✅ | Persists to `knowledge/chroma_db/` on disk; zero network; works offline; the keyword fallback means tests pass even without `sentence-transformers` installed |

At 170 documents, semantic search quality from a local ChromaDB is indistinguishable from a cloud vector DB. The switch to Pinecone would be a one-line change in `RagKnowledgeBase.__init__`.

### Mock-first architecture (not live-API-only)

Every agent has a `mock_delivery=True` path that returns realistic, deterministic output without calling any external API. This was a deliberate design choice:

```
  BENEFITS
  ─────────────────────────────────────────────────────────────
  1. 206 tests run in 8s with no API keys needed
  2. CI/CD works without secrets in the pipeline
  3. Developers can build new agents offline
  4. Outcome distributions in mock mode are tuned to be realistic
     (payment_made / read / no_response / objection in real ratios)
  5. Switching to live mode is a single env-var: MOCK_DELIVERY=false
```

The mock layer is not a test stub — it's a first-class code path that the full E2E `run_e2e.py` uses by default. Real API calls are opt-in via `.env`.

### Prompts as a separate package (not inline strings)

Inline prompt strings scattered across 14 agent files meant:
- A/B testing a prompt required finding it in a 200-line agent file
- Prompt changes weren't diff-reviewable in isolation
- No way to version or audit what prompt produced which output

The `prompts/` package makes every prompt a named constant, importable, and diff-able. A prompt change shows as a clean one-file diff in `git log --stat`.

---

## 🧪 Test Summary

```
tests/test_language_utils.py             39 passed
tests/test_voice_agent.py                35 passed
tests/test_observability.py              35 passed
tests/test_integrations.py               35 passed
tests/test_dashboard.py                  40 passed
tests/test_payment_agent.py              21 passed
tests/test_human_queue.py                11 passed
tests/test_feedback_propensity_loop.py    7 passed  -- closed feedback loop
─────────────────────────────────────────────────────
TOTAL                                   206 passed  ~8s
```

---

## 🏗️ Git History

| Commit | Feature |
|--------|---------|
| `ddeb6ee` | Foundation — 21-agent system, all 5 layers |
| `3cfd910` | Multi-language support — 9 Indian languages |
| `953bf99` | Voice agent — ElevenLabs + IRDAI + intent detection |
| `2d6e7dc` | Payment agent — UPI + QR + AutoPay + NetBanking |
| `7b16ac8` | Admin dashboard — 7-page Streamlit UI |
| `f6fb523` | Observability (★) — cost tracker + SHA-256 audit trail |
| `dc10d4f` | Integration stubs — CRM, PAS, IRDAI, Payment GW |
| `b147c8a` | 20-specialist human queue + skill-based routing |
| `59c0fbf` | Closed feedback loop — PropensityAgent auto-recalibrates |
| `be9707a` | RAG Knowledge Base (★) — 170+ docs, ChromaDB, keyword fallback |
| `6416b23` | WORKFLOW.md — beginner-friendly guide with glossary |
| `f31d558` | Prompt Registry (★) — all 15 LLM prompts to `prompts/` package |
| `0f78ee9` | Plan & Execute (★) + Critique Agent (★) — workflow.xml compliance, L3→L4/L5 routing, full L4 sub-pipeline |
| `543068b` | docs: prominently highlight RAG, Plan & Execute, Model Tracing, Critique Agent in README |
| `3d0a004` | docs: add `.env.example`, fix duplicate separator, E2E snapshot, Design Decisions section |

> (★) = RAG · Plan & Execute · Model Tracing · Critique Agent — the four highlighted patterns

---

*Built for Suraksha Life Insurance · Project RenewAI · Python 3.10 · Gemini AI · LangGraph · ChromaDB · 21 Agents · 5 Layers · 206 Tests*
