# 🔄 Project RenewAI — Workflow Guide

> **Who is this for?**
> This document is written for someone reading this codebase for the **first time**.
> It explains **what the system does**, **why each part exists**, and **how everything connects** — using plain English followed by visual diagrams.

---

## 📖 The Big Picture (Read This First)

Suraksha Life Insurance has thousands of customers whose life insurance policies are about to expire (called **"renewal due"**). Without renewal, the customer loses their coverage and the company loses revenue.

The old process: a human agent manually calls each customer. This doesn't scale.

**Project RenewAI** replaces that with an AI system that:
1. Figures out **which customers are most at risk** of not renewing
2. **Automatically contacts** them via WhatsApp, Email, or Voice call — in their own language
3. **Handles objections**, sends payment links, and processes payments
4. **Checks quality** of every message before sending
5. **Learns** from outcomes to get better over time
6. **Escalates** to a human only when truly needed

The system is built as **21 AI agents** grouped into **5 layers**, each with a specific job.

---

## 1. The 5-Layer Architecture

> **What you're looking at:** The complete system from top to bottom. Each box is an AI agent. The arrows show the order things happen.

```mermaid
graph TD
    CUST([👤 Customer\nPolicy Due for Renewal])

    subgraph L1["⚙️ LAYER 1 — STRATEGIC · decides WHAT to do"]
        SEG[Segmentation Agent\nGroups the customer:\nchampion / at_risk / dormant / churned]
        PROP[Propensity Scorer\nPredicts likelihood of NOT renewing\nlapse_score: 0 safe → 100 will lapse]
        TIME[Timing Optimizer\nFinds best day + time to contact\ne.g. avoid Mondays · contact after 6PM]
        CHAN[Channel Selector\nDecides: WhatsApp? Email? Voice? All three?]
        ORCH[Master Orchestrator\nAssembles the full journey plan\nand saves it to the database]
    end

    subgraph L2["📤 LAYER 2 — EXECUTION · actually SENDS messages"]
        DISP[Dispatcher\nReads the plan and\ntriggers the right agent]
        WA[WhatsApp Agent\nTwilio · in customer's language]
        EM[Email Agent\nSMTP · personalised HTML email]
        VO[Voice Agent\nElevenLabs TTS\nIRDAI: 8AM–8PM IST only]
        PAY[Payment Agent\nUPI link + QR code\nAutoPlay + NetBanking]
        OBJ[Objection Handler\nHandles: too expensive /\nwill think about it]
    end

    subgraph L3["✅ LAYER 3 — QUALITY · checks EVERY message before it goes out"]
        CRIT[Critique Agent\nGemini 2.5 Pro\nChecks: clarity · accuracy · tone]
        SAFE[Safety Agent\nBlocks harmful or\nmisleading content]
        COMP[Compliance Agent\nIRDAI rules: call window\ndisclosures · no mis-selling]
        SENT[Sentiment Agent\nDetects if tone feels\nthreatening or off]
        QSCO[Quality Scorer\n0–100 composite\n≥ 70 = send · below = human]
    end

    subgraph L4["📚 LAYER 4 — LEARNING · makes system SMARTER over time"]
        FEED[Feedback Loop\nReads outcomes: paid / no_response\nUpdates lapse_score in DB\nAuto-refreshes Propensity prompt]
        ABTM[A/B Test Manager\nMessage A vs B:\nwhich gets more renewals?]
        DRIF[Drift Detector\nAlerts if customer\nbehaviour is changing]
        REPO[Report Agent\nWeekly PDF report\nKPIs + recommendations]
    end

    subgraph L5["🧑 LAYER 5 — HUMAN · last resort when AI cannot handle it"]
        QM[Queue Manager\n20 Human Specialists\n6 teams · skill routing · SLA]
        SUPV[Supervisor Dashboard\n🟢 on-time · 🟡 at-risk · 🔴 breached]
    end

    CUST --> SEG
    SEG --> PROP --> TIME --> CHAN --> ORCH
    ORCH --> DISP
    DISP --> WA & EM & VO
    WA & EM & VO --> CRIT
    VO --> PAY
    WA --> OBJ
    CRIT --> SAFE --> COMP --> SENT --> QSCO
    QSCO -->|score ≥ 70| FEED
    QSCO -->|score < 70\nor flag| QM
    FEED --> ABTM --> DRIF --> REPO
    QM --> SUPV
    REPO -->|insights| ORCH
```

---

## 2. A Customer's Journey — Step by Step

> **What you're looking at:** A sequence diagram traces one customer's journey through the entire system. Time flows **downward**. Each horizontal arrow is one action. Read it like a script.

```mermaid
sequenceDiagram
    participant C as 👤 Customer
    participant L1 as ⚙️ Strategic Layer
    participant L2 as 📤 Execution Layer
    participant L3 as ✅ Quality Gate
    participant PAY as 💳 Payment Agent
    participant L5 as 🧑 Human Queue
    participant EXT as 🔌 External Systems

    Note over C,EXT: Policy renewal due — automated journey begins

    L1->>L1: Segment customer (champion/at_risk/dormant)
    L1->>L1: Score lapse propensity (0.0–1.0)
    L1->>L1: Pick optimal time + channel
    L1->>L2: Journey plan dispatched

    L2->>C: WhatsApp message (Twilio, local language)
    L2->>C: Email (SMTP, personalized)
    L2->>C: Voice call (ElevenLabs TTS, 8AM–8PM IST)

    L3->>L3: Critique → Safety → Compliance → Sentiment
    L3->>L3: Compute quality score 0–100

    alt score ≥ 70 — proceed
        L3->>L2: Approved — continue journey
        L2->>C: Send UPI deep link + QR code PNG
        C->>PAY: Customer clicks payment link
        PAY->>EXT: Razorpay webhook (payment.captured)
        PAY->>EXT: Update PAS (policy renewed)
        PAY->>EXT: Sync CRM (interaction logged)
        PAY->>EXT: IRDAI audit record
        PAY->>C: Confirmation + receipt
    else score < 70 or safety flag
        L3->>L5: Escalate with reason + context
        L5->>L5: Skill routing → assign specialist
        L5->>C: Human agent contacts customer
        L5->>EXT: IRDAI grievance filed if needed
    end

    L3->>L4: Feedback event stored
    L4->>L4: A/B test update + drift check
    L4->>L1: Model refresh insights
```

---

## 3. Payment Flow — How a Customer Pays

> **What you're looking at:** All the payment options the system can offer a customer. Every path eventually leads to Razorpay confirming the payment and the policy getting marked as renewed.

```mermaid
flowchart LR
    START([Payment\nTriggered]) --> BUILD[Build UPI\ndeep link\nNPCI spec]

    BUILD --> UPI["upi://pay\n?pa=suraksha.life@razorpay\n&pn=Suraksha Life\n&am=<premium>\n&cu=INR\n&tn=Renewal"]

    START --> QR[Generate\nQR Code PNG\nqrcode lib]
    QR --> B64[Base64 encode\nfor WhatsApp /\nemail embed]

    START --> AUTO{AutoPay\nMandate?}
    AUTO -->|yes| NACH[NACH / UPI\nAutoPay\nRazorpay Subscriptions]
    AUTO -->|no| NB[NetBanking\nlinks]

    NB --> BANKS["SBI • HDFC • ICICI • AXIS\nKOTAK • BOB • PNB • UNION"]

    UPI & NACH & BANKS --> SEND[Send to\nCustomer]

    SEND --> WH{Webhook\nreceived}
    WH -->|payment.captured| SUCCESS[✅ Success\nupdate PAS + CRM]
    WH -->|payment.failed| RETRY[🔁 Retry\nwith alt channel]
    WH -->|refund| REFUND[💸 Refund\nlog in audit trail]

    SUCCESS --> IRDAI[IRDAI\naudit record]
```

---

## 4. Human Escalation — Who Gets the Case

> **What you're looking at:** Not every case can be handled by AI. When a quality check fails, a customer is distressed, or a payment fails, the case goes to a human. This diagram shows exactly how the right specialist is picked.

```mermaid
flowchart TD
    TRIG([Escalation\nTriggered]) --> REASON{Escalation\nReason}

    REASON --> D1[distress / bereavement]
    REASON --> D2[mis_selling / legal]
    REASON --> D3[complaint / medical]
    REASON --> D4[payment_failure / mandate]
    REASON --> D5[requested_human / upsell]
    REASON --> D6[P1 Urgent]

    D1 --> WELL["🧠 WELLNESS TEAM\nAGT-016 · AGT-017 · AGT-018\nSkill: distress, bereavement,\nsenior_citizen"]
    D2 --> CTEAM["⚖️ COMPLIANCE TEAM\nAGT-010 · AGT-011 · AGT-012\nSkill: mis_selling, legal, irdai"]
    D3 --> CLAIMS["🏥 CLAIMS TEAM\nAGT-006 · AGT-007\nAGT-008 · AGT-009\nSkill: medical, complaint"]
    D4 --> TECH["💻 TECH TEAM\nAGT-013 · AGT-014 · AGT-015\nSkill: payment, mandate"]
    D5 --> RENEW["📋 RENEWAL TEAM\nAGT-001–005\nSkill: renewal, upsell"]
    D6 --> SENIOR["🌟 SENIOR MGR\nAGT-019 · AGT-020\nAll skills · Any language"]

    WELL & CTEAM & CLAIMS & TECH & RENEW & SENIOR --> ROUTE{Tier routing}

    ROUTE --> T1["Tier 1\nSkill + Language match"]
    ROUTE --> T2["Tier 2\nSkill only match"]
    ROUTE --> T3["Tier 3\nAny available"]

    T1 & T2 & T3 --> SLA{SLA}

    SLA --> P1["P1 Urgent\n⏱ 1 hour"]
    SLA --> P2["P2 High\n⏱ 4 hours"]
    SLA --> P3["P3 Normal\n⏱ 24 hours"]
    SLA --> P4["P4 Low\n⏱ 72 hours"]

    P1 & P2 & P3 & P4 --> SUPV[Supervisor\nDashboard\nSLA RAG status]
```

---

## 5. Quality Gate — Every Message Gets Checked

> **What you're looking at:** Before ANY message leaves the system, it passes through 5 checks in sequence. Think of it as airport security — one failed check and the message doesn't go out. Score ≥ 70 = approved. Score < 70 = blocked and escalated to a human.

```mermaid
flowchart TD
    MSG([Outbound\nMessage]) --> CRIT

    subgraph QG["✅ QUALITY GATE"]
        CRIT[Critique Agent\nGemini 2.5 Pro\nclarity · accuracy · tone]
        CRIT --> SAFE[Safety Agent\nGemini 2.5 Flash\nno harmful content]
        SAFE --> COMP[Compliance Agent\nIRDAI regulations\ncall window: 8AM–8PM IST]
        COMP --> SENT[Sentiment Agent\npositive / neutral / negative]
        SENT --> QSCO[Quality Scorer\n0–100 composite]
    end

    QSCO --> THRESHOLD{Score ≥ 70?}
    THRESHOLD -->|yes ✅| PASS[PASS\nSend to customer\nlog feedback event]
    THRESHOLD -->|no ❌| BLOCK[BLOCK\nEscalate to human\nflag for review]

    SAFE -->|unsafe flag| BLOCK
    COMP -->|IRDAI violation| BLOCK
```

---

## 6. Observability — Tracking Cost and Compliance

> **What you're looking at:** Every single API call does two things automatically: (1) logs its cost so we don't overspend, and (2) writes a tamper-evident audit entry for IRDAI compliance. Both happen without any agent needing to think about it.

```mermaid
flowchart LR
    subgraph EVENTS["Every API Call"]
        G1[Gemini Flash\n$0.00015/$0.00060\nper 1K tokens]
        G2[Gemini Pro\n$0.00125/$0.00500\nper 1K tokens]
        EL[ElevenLabs\n$0.0003 per 1K chars]
        TW[Twilio\n$0.005 per message]
        RZ[Razorpay\n$0.002 per txn]
    end

    G1 & G2 & EL & TW & RZ --> CT[Cost Tracker\nSQLite cost_events]

    CT --> USD[USD amount]
    CT --> INR["INR amount\n(×84 exchange rate)"]
    CT --> DAILY{Daily total\n≥ ₹500?}

    DAILY -->|yes 🔔| ALERT[Budget Alert\nlog warning]
    DAILY -->|no ✅| OK[Continue]

    subgraph AUDIT["Audit Trail — IRDAI Compliant"]
        direction TB
        AT1[COMMUNICATION\nall outreach messages]
        AT2[PAYMENT\ntransaction events]
        AT3[ESCALATION\nhuman handoff]
        AT4[COMPLIANCE\nIRDAI filings]
        AT5[DATA_ACCESS\nPII queries]
        AT6[AGENT_ACTION\nall AI decisions]
    end

    G1 & TW & RZ --> AUDIT
    AUDIT --> HASH[SHA-256 chain hash\ntamper-evident\n5-year retention]
```

---

## 7. The Closed Feedback Loop — How the AI Gets Smarter

> **What you're looking at:** This is what separates RenewAI from a static rule-based system. After enough real-world outcomes accumulate (customers paid or lapsed), the Propensity Agent's Gemini prompt is **automatically updated** with those real examples. The next scoring run is therefore more accurate — no retraining, no manual work.

```mermaid
flowchart TD
    FB([Feedback\nEvent]) --> FL[Feedback Loop\nstore outcome +\nresponse metadata]

    FL --> AB[A/B Test Manager\ntracks variant performance\nstatistical significance]
    FL --> DD[Drift Detector\nmonitor feature distributions\nJensen-Shannon divergence]

    AB --> WINNER{Winner\ndetected?}
    WINNER -->|yes| PROMOTE[Promote variant\nupdate default template]
    WINNER -->|no| CONTINUE[Continue test]

    DD --> DRIFT{Drift\ndetected?}
    DRIFT -->|yes| RETRAIN[Flag for\nmodel refresh]
    DRIFT -->|no| MONITOR[Keep monitoring]

    FL & AB & DD --> REPO[Report Agent\nweekly KPIs +\ncohort analysis]

    REPO --> INSIGHTS[Insights delivered\nto Orchestrator]
    INSIGHTS --> ORCH([Orchestrator\nupdated strategy])
```

---

## 8. Data — What's Stored and Where

> **What you're looking at:** All data lives in a single SQLite file (`data/renewai.db`). This diagram shows which tables exist, which layer writes to each one, and which external systems also get updated when actions happen.

```mermaid
flowchart LR
    subgraph DB["SQLite — renewai.db"]
        T1[(customers)]
        T2[(policies)]
        T3[(renewal_journeys)]
        T4[(interactions)]
        T5[(escalation_cases)]
        T6[(quality_scores)]
        T7[(feedback_events)]
        T8[(ab_test_results)]
        T9[(drift_reports)]
        T10[(customer_memory)]
        T11[(cost_events)]
        T12[(audit_trail)]
    end

    subgraph EXT["External Systems (Stubs → Real in Prod)"]
        CRM[CRM\nSalesforce/Zoho]
        PAS[PAS\nDuckCreek/Majesco]
        IRDAI_P[IRDAI Portal\nBima Bharosa]
        RZP[Razorpay\nPayment Gateway]
    end

    subgraph KB["Knowledge Base"]
        CHROMA[ChromaDB\n56 documents\nKeyword fallback]
    end

    subgraph MEM["Customer Memory"]
        CMEM[customer_memory.py\nSQLite per customer\nconversation history]
    end

    AGENTS([All Agents]) --> T3 & T4 & T6 & T7
    AGENTS --> T11 & T12
    L5([Human Layer]) --> T5
    L4([Learning Layer]) --> T8 & T9
    MEM --> T10

    AGENTS --> CRM & PAS
    PAY_AGENT([Payment Agent]) --> RZP
    COMP_AGENT([Compliance Agent]) --> IRDAI_P

    ORCH([Orchestrator]) --> CHROMA
    AGENTS --> CMEM
```

---

## 9. Voice Call — Language + IRDAI Compliance

> **What you're looking at:** A voice call is the most complex channel. It must first check whether calling is even legally allowed right now (IRDAI: 8AM–8PM IST only), then detect what the customer needs, generate a script in their language, and handle any objections — all in real time.

```mermaid
sequenceDiagram
    participant ORCH as Orchestrator
    participant VA as Voice Agent
    participant EL as ElevenLabs API
    participant IRDAI as IRDAI Checker
    participant C as 📱 Customer

    ORCH->>VA: trigger_call(customer_id, language="hi")

    VA->>IRDAI: check_call_window(IST now)
    alt Outside 8AM–8PM IST
        IRDAI-->>VA: BLOCKED — outside permitted hours
        VA->>ORCH: call deferred to next window
    else Within window
        IRDAI-->>VA: ALLOWED

        VA->>VA: detect_intent(customer_history)
        Note over VA: renewal_reminder / objection_handling\npayment_assistance / general_query

        VA->>VA: generate_script(language="hi", intent)
        Note over VA: नमस्ते! आपकी पॉलिसी नवीनीकरण...

        VA->>EL: synthesize_speech(text_hi, voice_id, model=eleven_multilingual_v2)
        EL-->>VA: audio_bytes (MP3)

        VA->>C: play audio / stream call
        C-->>VA: response (intent detected)

        alt Objection raised
            VA->>VA: objection_handler.handle(objection_type)
            VA->>EL: synthesize_response(language="hi")
            EL-->>VA: audio_bytes
            VA->>C: play rebuttal
        end

        VA->>ORCH: call_result(outcome, transcript)
    end
```

---

## 10. Admin Dashboard — 7 Pages

> **What you're looking at:** The Streamlit dashboard that a business analyst or ops manager uses daily to monitor the system. Run it with `streamlit run dashboard/app.py` then open `http://localhost:8501`.

```mermaid
graph LR
    DASH[🖥️ Streamlit Dashboard\nlocalhost:8501]

    DASH --> P1[📊 Overview\nKPI cards · renewal rate\nchannel breakdown · trend]
    DASH --> P2[🗺️ Journeys\nactive journeys table\nstatus filters]
    DASH --> P3[👥 Customers\ndrill-down per customer\nmessage history · quality]
    DASH --> P4[⭐ Quality\nquality score trends\nby agent / channel]
    DASH --> P5[🚨 Escalations\nopen cases · SLA RAG\n🟢 on-time 🟡 at-risk 🔴 breached]
    DASH --> P6[📅 Renewals Due\n30/60/90-day pipeline\nrevenue at risk]
    DASH --> P7[⚙️ Settings\nconfiguration · API health\ncost summary]
```

---

## 11. The Closed Feedback Loop — System Gets Smarter Over Time

> **What you're looking at:** This is the self-improvement engine. Every time a customer **pays** or **lapses**, the system records the outcome, and the `FeedbackLoopAgent` uses those real outcomes to rewrite the examples it gives to the `PropensityAgent`. The next batch of customers gets scored using a prompt that reflects what actually happened — not just what was assumed at training time.

```mermaid
flowchart TD
    A([Customer Outcome\nrecorded in DB\npaid / no_response / escalated]) --> B[FeedbackLoopAgent.run\ncollects outcomes from\nfeedback_events table]

    B --> C{≥ 10 strong-signal\nevents collected?}

    C -- No --> D[Skip refresh\nuse existing prompt]
    C -- Yes --> E[PropensityAgent.refresh_from_feedback\nreads top 5 PAID + top 5 LAPSED\nfrom real outcomes]

    E --> F[Builds few-shot block\ne.g. age=42 · city=Mumbai · score=0.87 → PAID\nage=58 · city=Pune · score=0.21 → LAPSED]

    F --> G[Stores in module cache\n_FEEDBACK_FEW_SHOT]

    G --> H[Next call to PropensityAgent.run\ninjects few-shot block at top of\nGemini prompt automatically]

    H --> I([Gemini sees real past examples\nbefore scoring the new customer\n→ more accurate lapse_score])

    I --> J[FeedbackSummary returned\n• events_processed\n• score_updates\n• propensity_prompt_refreshed = True])
```

**Key files:**
| File | What it does |
|------|-------------|
| `agents/layer1_strategic/propensity.py` | Holds `refresh_from_feedback()` + `_FEEDBACK_FEW_SHOT` cache |
| `agents/layer4_learning/feedback_loop.py` | Auto-triggers refresh when threshold is met |
| `agents/layer1_strategic/orchestrator.py` | `run_batch_with_feedback()` — run a batch + auto-learn |
| `tests/test_feedback_propensity_loop.py` | 7 tests covering the full loop |

---

## 12. Quick-Start — Run the System in 5 Steps

> **What you're looking at:** The exact commands to go from a fresh clone to a running system. Copy-paste these in order.

```mermaid
flowchart LR
    S1["① Clone\ngit clone https://github.com/Brohammad/InsuranceAI\ncd InsuranceAI"] --> S2

    S2["② Install dependencies\npython -m venv .venv\nsource .venv/bin/activate\npip install -r requirements.txt"] --> S3

    S3["③ Set API keys\ncp .env.example .env\nnano .env\n→ add GEMINI_API_KEY + TWILIO_ + ELEVENLABS_"] --> S4

    S4["④ Seed the database\npython data/seed.py\n→ creates 20 customers + 20 policies\nin data/renewai.db"] --> S5

    S5["⑤ Run tests + launch\npytest  ← 225 tests\nstreamlit run dashboard/app.py\n→ open http://localhost:8501"]
```

**Optional extras:**
```bash
# Run only end-to-end tests (hits real Gemini API — costs tokens):
pytest -m e2e

# Run a single batch with automatic feedback learning:
python -c "
from agents.layer1_strategic.orchestrator import run_batch_with_feedback
# pass list of (Customer, Policy) tuples
result = run_batch_with_feedback(pairs)
print(result['feedback'])
"
```

---

## 13. Glossary

> **First-time reader?** Here are all the terms used in this document and the codebase.

| Term | What it means |
|------|---------------|
| **lapse_score** | A number from 0 to 100 that estimates how likely a customer is to NOT renew. 0 = almost certain to renew. 100 = almost certain to lapse. Computed by the Propensity Agent using Gemini. |
| **champion** | A customer segment. Champions renew on time, have high NPS, and rarely need nudging. |
| **at_risk** | A customer segment. These customers missed past payments or showed price sensitivity. High priority for the system. |
| **dormant** | A customer segment. No engagement for 6+ months. The system tries to re-activate them. |
| **churned** | A customer segment. Already lapsed. System attempts win-back with a special offer. |
| **IRDAI** | Insurance Regulatory and Development Authority of India. The government body that sets rules for insurance. The system enforces IRDAI call hours (8 AM–8 PM IST) and disclosure requirements automatically. |
| **PAS** | Policy Administration System. The core database that stores policy records for an insurance company. The system integrates with it via a stub (`integrations/pas_stub.py`). |
| **CRM** | Customer Relationship Management system. Stores customer contact history. The system pushes journey updates to it via a stub (`integrations/crm_stub.py`). |
| **UPI** | Unified Payments Interface. India's real-time payment system (PhonePe, GPay, Paytm). The Payment Agent generates UPI deep-links and QR codes. |
| **NACH** | National Automated Clearing House. India's system for recurring auto-debit mandates. Used for AutoPay renewals. |
| **TTS** | Text-to-Speech. The Voice Agent uses ElevenLabs TTS to synthesize audio in the customer's language. |
| **RAG** | Retrieval-Augmented Generation. The Knowledge Base layer — agents look up product docs and FAQs before generating answers, so Gemini doesn't hallucinate policy details. |
| **few-shot** | A prompting technique where you give the AI 2–5 real examples before asking it to do a task. The feedback loop builds a few-shot block from real paid/lapsed outcomes. |
| **SLA** | Service Level Agreement. The maximum time allowed to resolve an escalated case. The Queue Manager tracks 🟢 on-time / 🟡 at-risk / 🔴 breached. |
| **drift** | When customer behaviour starts changing in ways the model wasn't trained for. The Drift Detector alerts ops when this happens. |
| **A/B test** | Sending message variant A to half the customers and variant B to the other half, then measuring which gets more renewals. |
| **stub** | A placeholder integration that mimics a real external system (CRM, PAS, payment gateway) without actually calling it. Stubs live in `integrations/`. |
| **Gemini** | Google's large language model (LLM), specifically `gemini-2.5-pro` and `gemini-2.5-flash`. The AI brain behind all content generation and scoring. |

---

*Project RenewAI · Suraksha Life Insurance · 21 Agents · 5 Layers · 225 Tests*
*All Mermaid diagrams render natively on GitHub and in VS Code with the Mermaid Preview extension.*
