# 🛡️ Project RenewAI — Suraksha Life Insurance

> **AI-powered policy renewal system** — 21 autonomous agents across 5 layers, handling WhatsApp · Email · Voice outreach, UPI payments, IRDAI compliance, and human escalation for life insurance renewal.

---

## 📐 System Architecture

```
╔══════════════════════════════════════════════════════════════════════════════════════╗
║                          PROJECT RENEWAI — 5-LAYER AGENT SYSTEM                     ║
╠══════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                      ║
║  ┌─────────────────────────────────────────────────────────────────────────────┐    ║
║  │  LAYER 1 — STRATEGIC  (Gemini 3.1 Pro)                                      │    ║
║  │                                                                               │    ║
║  │  [Segmentation] → [Propensity Score] → [Timing Optimizer] → [Channel        │    ║
║  │   Selector] → [Master Orchestrator]                                           │    ║
║  └──────────────────────────────┬────────────────────────────────────────────────┘    ║
║                                 │ journey plan                                        ║
║  ┌──────────────────────────────▼────────────────────────────────────────────────┐    ║
║  │  LAYER 2 — EXECUTION  (Gemini 3 Flash)                                        │    ║
║  │                                                                               │    ║
║  │  [Dispatcher] → [WhatsApp Agent] │ [Email Agent] │ [Voice Agent]             │    ║
║  │                → [Payment Agent] │ [Objection Handler]                       │    ║
║  └──────────────────────────────┬────────────────────────────────────────────────┘    ║
║                                 │ messages + results                                  ║
║  ┌──────────────────────────────▼────────────────────────────────────────────────┐    ║
║  │  LAYER 3 — QUALITY & SAFETY  (Gemini 2.5 Pro + Flash)                        │    ║
║  │                                                                               │    ║
║  │  [Critique Agent] → [Safety Agent] → [Compliance Agent] → [Sentiment] →     │    ║
║  │  [Quality Scorer]                                                             │    ║
║  └──────────────────────────────┬────────────────────────────────────────────────┘    ║
║                                 │ scores + flags                                      ║
║  ┌──────────────────────────────▼────────────────────────────────────────────────┐    ║
║  │  LAYER 4 — LEARNING  (Gemini 3 Flash)                                         │    ║
║  │                                                                               │    ║
║  │  [Feedback Loop] → [A/B Test Manager] → [Drift Detector] → [Report Agent]   │    ║
║  └──────────────────────────────┬────────────────────────────────────────────────┘    ║
║                                 │ escalation trigger                                  ║
║  ┌──────────────────────────────▼────────────────────────────────────────────────┐    ║
║  │  LAYER 5 — HUMAN ESCALATION                                                   │    ║
║  │                                                                               │    ║
║  │  [Queue Manager] → [20 Specialists] → [Supervisor Dashboard]                 │    ║
║  └───────────────────────────────────────────────────────────────────────────────┘    ║
║                                                                                      ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
```

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
                    │  lapse_score: 0.0–1.0   │
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
    │  SCORE ≥ 70      │              │   SCORE < 70 OR     │
    │  ✅ CONTINUE      │              │   SAFETY FLAG       │
    │                  │              │   🚨 ESCALATE       │
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
│  Hindi  hi   │  नमस्ते             │  UP, MP, Bihar, Delhi, Raj     │
│  English en  │  Hello             │  Pan-India default             │
│  Tamil   ta  │  வணக்கம்           │  Tamil Nadu, Sri Lanka         │
│  Telugu  te  │  నమస్కారం          │  Andhra, Telangana             │
│  Kannada kn  │  ನಮಸ್ಕಾರ           │  Karnataka                     │
│  Malayalam ml│  നമസ്കാരം          │  Kerala                        │
│  Bengali bn  │  নমস্কার            │  West Bengal, Bangladesh       │
│  Marathi mr  │  नमस्कार           │  Maharashtra                   │
│  Gujarati gu │  નમસ્તે            │  Gujarat                       │
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

## 🔭 Observability Stack

```
  EVERY API CALL
       │
       ├──► COST TRACKER ──────► SQLite cost_events table
       │    • Gemini (per model, in/out tokens)        Daily budget: ₹500
       │    • ElevenLabs (per 1K chars)                Alert on breach
       │    • Twilio (per message)
       │    • Razorpay (per transaction)
       │
       └──► AUDIT TRAIL ───────► SQLite audit_trail table (append-only)
            • SHA-256 chain hash (tamper-evident)
            • Categories: COMMUNICATION │ PAYMENT │ ESCALATION
            │             DATA_ACCESS │ AGENT_ACTION │ COMPLIANCE
            └── IRDAI 5-year retention compliant
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
│   ├── layer3_quality/          # Critique, Safety, Compliance, Sentiment, Quality Scorer
│   ├── layer4_learning/         # Feedback Loop, A/B Manager, Drift Detector, Report Agent
│   └── layer5_human/            # Queue Manager (20 specialists), Supervisor Dashboard
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
├── observability/
│   ├── cost_tracker.py          # Token + API cost tracking (₹ + USD)
│   └── audit_trail.py           # IRDAI-compliant append-only audit log
│
├── knowledge/                   # RAG knowledge base (56 documents)
├── memory/                      # Customer memory store (ChromaDB + SQLite)
├── data/
│   ├── seed.py                  # Sample data seeder
│   └── renewai.db               # SQLite database
│
├── tests/                       # 218 unit tests (5.45s)
│   ├── test_dashboard.py        # 40 tests
│   ├── test_observability.py    # 35 tests
│   ├── test_integrations.py     # 35 tests
│   ├── test_voice_agent.py      # 35 tests
│   ├── test_language_utils.py   # 39 tests
│   ├── test_payment_agent.py    # 21 tests
│   ├── test_human_queue.py      # 11 tests
│   └── test_final_integration.py# 5 e2e tests (real Gemini — run with -m e2e)
│
├── pytest.ini                   # Default: skip e2e tests
├── requirements.txt
└── .env                         # API keys (gitignored)
```

---

## ⚙️ Tech Stack

| Component | Technology |
|-----------|-----------|
| LLM — Orchestration | Gemini 3.1 Pro Preview |
| LLM — Execution | Gemini 3 Flash Preview |
| LLM — Critique/Review | Gemini 2.5 Pro |
| LLM — Safety/Classify | Gemini 2.5 Flash |
| Voice TTS | ElevenLabs `eleven_multilingual_v2` |
| WhatsApp | Twilio Sandbox |
| Email | SMTP (MailHog local / SendGrid prod) |
| Payments | Razorpay — UPI, QR, AutoPay, NetBanking |
| Vector DB | ChromaDB (keyword fallback) |
| Database | SQLite |
| Dashboard | Streamlit + Plotly |
| Testing | pytest — 218 tests |
| Language | Python 3.10 |

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
# Add: GEMINI_API_KEY, ELEVENLABS_API_KEY, TWILIO_*, RAZORPAY_*

# 3. Seed database
python data/seed.py

# 4. Run tests (218 fast unit tests)
pytest                        # unit tests only  (~5s)
pytest -m e2e                 # full e2e with real Gemini (~14min)

# 5. Launch dashboard
streamlit run dashboard/app.py
# → http://localhost:8501
```

---

## 🧪 Test Summary

```
tests/test_language_utils.py   ████████████████████  39 passed
tests/test_voice_agent.py      ██████████████████    35 passed
tests/test_observability.py    ██████████████████    35 passed
tests/test_integrations.py     ██████████████████    35 passed
tests/test_dashboard.py        ████████████████████  40 passed
tests/test_payment_agent.py    ███████████           21 passed
tests/test_human_queue.py      ██████                11 passed
─────────────────────────────────────────────────────────────
TOTAL                                               218 passed  ⚡ 5.45s
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
| `f6fb523` | Observability — cost tracker + audit trail |
| `dc10d4f` | Integration stubs — CRM, PAS, IRDAI, Payment GW |
| `b147c8a` | 20-specialist human queue + skill-based routing |

---

*Built for Suraksha Life Insurance · Project RenewAI · Python 3.10 · Gemini AI*
