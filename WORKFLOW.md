# 🔄 Project RenewAI — Complete Workflow Diagrams

> Detailed flow diagrams for every subsystem of the 21-agent insurance renewal platform.

---

## 1. End-to-End System Architecture

```mermaid
graph TD
    CUST([👤 Customer\nPolicy Due for Renewal])

    subgraph L1["⚙️ LAYER 1 — STRATEGIC"]
        SEG[Segmentation Agent\nchampion / at_risk / dormant]
        PROP[Propensity Scorer\nlapse_score 0.0–1.0]
        TIME[Timing Optimizer\nbest time + day]
        CHAN[Channel Selector\nWhatsApp / Email / Voice]
        ORCH[Master Orchestrator\nbuilds journey plan]
    end

    subgraph L2["📤 LAYER 2 — EXECUTION"]
        DISP[Dispatcher]
        WA[WhatsApp Agent\nTwilio]
        EM[Email Agent\nSMTP]
        VO[Voice Agent\nElevenLabs]
        PAY[Payment Agent\nRazorpay]
        OBJ[Objection Handler\nGemini]
    end

    subgraph L3["✅ LAYER 3 — QUALITY"]
        CRIT[Critique Agent\nGemini 2.5 Pro]
        SAFE[Safety Agent]
        COMP[Compliance Agent\nIRDAI rules]
        SENT[Sentiment Agent]
        QSCO[Quality Scorer\n0–100]
    end

    subgraph L4["📚 LAYER 4 — LEARNING"]
        FEED[Feedback Loop]
        ABTM[A/B Test Manager]
        DRIF[Drift Detector]
        REPO[Report Agent]
    end

    subgraph L5["🧑 LAYER 5 — HUMAN"]
        QM[Queue Manager\n20 Specialists]
        SUPV[Supervisor Dashboard]
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

## 2. Customer Renewal Journey — Sequence Diagram

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

## 3. Payment Processing Flow

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

## 4. Human Escalation & Skill Routing

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

## 5. Quality Gate — Layer 3 Detail

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

## 6. Observability & Cost Tracking

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

## 7. Layer 4 — Learning & Adaptation Loop

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

## 8. Data Flow — Databases & Integrations

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

## 9. Multi-Language Voice Call Flow

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

## 10. Admin Dashboard — Pages Overview

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

*Project RenewAI · Suraksha Life Insurance · All diagrams render in GitHub · VS Code Mermaid Preview*
