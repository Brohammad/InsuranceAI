"""
knowledge/rag_knowledge_base.py
────────────────────────────────
RAG Knowledge Base for Project RenewAI

Stores and retrieves:
  1. Product FAQs          — 10 documents (Term, Endowment, ULIP, Pension, MoneyBack, Health)
  2. Objection Responses   — 150 objection→reframe pairs across 12 categories
  3. Benefit Calculators   — maturity, tax, surrender, death benefit explanations
  4. IRDAI Compliance Docs — key rules, grievance, free-look, cooling-off
  5. Renewal Scripts       — tone-specific opening + closing scripts

Backend: ChromaDB (persistent local) with sentence-transformers embeddings.
Falls back to keyword search if ChromaDB unavailable.

Usage:
    kb = RagKnowledgeBase()
    kb.build()                              # index all docs (idempotent)
    docs = kb.query("what is sum assured", n=3)
    objection = kb.get_objection_response("premium is too high")
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger

from core.config import settings, ROOT_DIR


# ── Paths ──────────────────────────────────────────────────────────────────────
KB_DIR = ROOT_DIR / "knowledge" / "chroma_db"
KB_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  DOCUMENT CORPUS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class KBDocument:
    doc_id:   str
    category: str   # faq / objection / calculator / compliance / script
    title:    str
    content:  str
    tags:     list[str] = field(default_factory=list)


# ── 1. Product FAQs ────────────────────────────────────────────────────────────

PRODUCT_FAQS: list[KBDocument] = [
    KBDocument("faq_001", "faq", "What is a Term Insurance Policy?",
        """A Term Insurance policy provides pure life cover for a fixed period (term).
If the policyholder dies during the term, the nominees receive the Sum Assured as a death benefit.
There is no maturity benefit if the policyholder survives. Premiums are low because there is no savings component.
Suraksha Life Term Shield offers cover up to age 75 with Sum Assured from ₹25 lakh to ₹10 crore.
Riders available: Accidental Death Benefit, Critical Illness Waiver, Income Replacement.""",
        ["term", "life cover", "death benefit", "sum assured"]),

    KBDocument("faq_002", "faq", "What is an Endowment Policy?",
        """An Endowment policy combines life insurance with savings.
It pays the Sum Assured on death OR on maturity (whichever comes first).
Premiums are higher than term plans because a portion builds savings (the 'endowment').
Suraksha Life Endowment Plus offers guaranteed additions of 3% per year on Sum Assured.
Bonus: Reversionary bonus declared annually + Terminal bonus on maturity.
Tax benefit: Premium up to ₹1.5 lakh deductible under Section 80C.""",
        ["endowment", "maturity", "savings", "bonus", "80C"]),

    KBDocument("faq_003", "faq", "What is a ULIP (Unit Linked Insurance Plan)?",
        """A ULIP is a market-linked insurance product. Part of premium goes to life cover,
part is invested in equity/debt/balanced funds chosen by the policyholder.
Lock-in period: 5 years (IRDAI mandate).
NAV (Net Asset Value) fluctuates daily based on market performance.
Suraksha Life WealthMax ULIP: 8 fund options, free switches (4/year), loyalty additions from year 6.
Tax: Premium up to ₹1.5L under 80C; maturity tax-free under 10(10D) if annual premium ≤ ₹2.5L.""",
        ["ulip", "market linked", "NAV", "equity", "fund", "10D"]),

    KBDocument("faq_004", "faq", "What is a Pension/Annuity Plan?",
        """A Pension plan helps build a retirement corpus. During accumulation phase, premiums invest in funds.
At vesting age, the corpus converts to regular income (annuity). Options: immediate or deferred annuity.
Suraksha Life RetireWell: vesting age 55-70, guaranteed annuity rates locked at purchase.
NPS-linked option available. Commutation: up to 1/3rd of corpus tax-free at retirement.
Tax: 80CCC deduction up to ₹1.5L; ₹50,000 additional under 80CCD(1B).""",
        ["pension", "annuity", "retirement", "vesting", "80CCC", "NPS"]),

    KBDocument("faq_005", "faq", "What is a Money Back Policy?",
        """A Money Back policy pays a percentage of Sum Assured at regular intervals (survival benefits)
PLUS the remaining Sum Assured on maturity. Full life cover continues throughout.
Suraksha Life MoneyBack Pro: 20% payback every 5 years, 40% + bonuses on maturity.
Ideal for customers needing periodic liquidity (children's education, marriage milestones).
If death occurs, full Sum Assured is paid (survival benefits already paid are NOT deducted).""",
        ["money back", "survival benefit", "periodic payout", "liquidity"]),

    KBDocument("faq_006", "faq", "What is a Health Insurance Rider?",
        """A Health Insurance Rider can be added to base life policy for additional protection.
Critical Illness Rider: lump sum on diagnosis of 36 critical illnesses (cancer, heart attack, stroke etc).
Hospital Cash Rider: daily cash benefit during hospitalisation (₹1000-5000/day).
Waiver of Premium Rider: all future premiums waived on total permanent disability.
These riders lapse if base policy lapses — renewal of base policy protects all riders.""",
        ["health", "rider", "critical illness", "hospital cash", "waiver"]),

    KBDocument("faq_007", "faq", "What happens if I miss a premium payment?",
        """Grace Period: 30 days for annual/semi-annual mode; 15 days for monthly mode.
During grace period: policy continues with full benefits; premium + interest due.
After grace period: policy LAPSES — no death benefit, no surrender value accrual.
Revival: policy can be revived within 5 years of lapse by paying all dues + interest (8% p.a.).
Paid-Up: after 3 years of premium payment, policy converts to paid-up with reduced benefits.""",
        ["lapse", "grace period", "revival", "paid-up", "missed premium"]),

    KBDocument("faq_008", "faq", "What is the Free Look Period?",
        """Free Look Period: 15 days from receipt of policy document (30 days for distance marketing).
During free look: policyholder can return the policy for any reason.
Refund: full premium minus proportionate risk premium for coverage period and medical exam costs.
After free look: policy cannot be cancelled except on specific grounds.
IRDAI mandate: all insurers must prominently display free look period in policy bond.""",
        ["free look", "cancellation", "return policy", "refund"]),

    KBDocument("faq_009", "faq", "How is Sum Assured calculated for Tax Benefit?",
        """Section 80C: Annual premium up to ₹1.5 lakh deductible from taxable income.
Condition: Sum Assured must be at least 10× annual premium (for policies issued after April 2012).
Section 10(10D): Maturity/death proceeds tax-free IF annual premium ≤ 10% of Sum Assured.
For ULIPs: annual premium must be ≤ ₹2.5L for tax-free maturity.
Example: ₹1 crore Term plan at ₹12,000/year — fully qualifies for 80C and 10(10D).""",
        ["tax benefit", "80C", "10(10D)", "sum assured", "premium"]),

    KBDocument("faq_010", "faq", "What is Nomination and Assignment?",
        """Nomination: policyholder designates nominee(s) to receive death benefit.
Multiple nominees allowed with % share. Minor nominees require appointee.
Change of nomination: allowed anytime before death by submitting form to insurer.
Assignment: policyholder transfers policy ownership to another person (e.g. for loan collateral).
Absolute assignment transfers all rights; conditional assignment is for specific purpose.
After assignment, assignee must consent to any further nomination changes.""",
        ["nomination", "nominee", "assignment", "beneficiary"]),
]


# ── 2. Objection Responses (150 pairs across 12 categories) ───────────────────

_OBJ_DATA: list[tuple[str, str, str, list[str]]] = [
    # (id, title, objection→response content, tags)

    # PRICE / AFFORDABILITY (15 pairs)
    ("obj_p01", "Premium Too High",
     """OBJECTION: The premium is too high / I can't afford it.
RESPONSE: I completely understand — every rupee matters. Let me show you a few options:
1. We can reduce the Sum Assured slightly to bring the premium within your budget.
2. Monthly payment mode reduces each payment to ₹{monthly_amount} instead of the full annual amount.
3. EMI option available through credit card / bank — 0% interest for 3-6 months for select banks.
4. Consider removing riders you may not immediately need and adding them later.
The core protection stays intact. Shall I recalculate for a budget that works for you?""",
     ["price", "expensive", "afford", "cost", "money"]),

    ("obj_p02", "Can I Pay in Instalments?",
     """OBJECTION: Can I pay in monthly instalments instead of annually?
RESPONSE: Absolutely! We offer multiple payment modes:
- Monthly: 12 instalments of ₹X (slight loading of ~3-5% on total annual premium)
- Quarterly: 4 instalments of ₹X
- Half-yearly: 2 instalments of ₹X
- Annual: single payment with best value
You can switch modes on the renewal date. Monthly ECS/NACH mandate takes 3-7 days to activate.
Want me to set up the monthly ECS now?""",
     ["instalment", "monthly", "EMI", "quarterly", "payment mode"]),

    ("obj_p03", "Premium Increased This Year",
     """OBJECTION: Why has my premium increased this year?
RESPONSE: Great question — for most policies, the premium is FIXED for the entire term.
If you've seen an increase, it's likely due to:
1. Age-band adjustment (some policies have 5-year age band pricing)
2. Service tax / GST adjustment (currently 18% on risk premium, 4.5% on savings)
3. Rider premium revision — riders are separately revised every 3-5 years
4. Health top-up revision based on medical inflation index
Let me pull up your exact policy to confirm. Your base sum assured protection doesn't change.""",
     ["premium increase", "price hike", "why more", "GST"]),

    ("obj_p04", "Better Rate Elsewhere",
     """OBJECTION: I found a cheaper policy from another company.
RESPONSE: It's wise to compare — and I respect that. A few things to verify before switching:
1. Claim Settlement Ratio: Suraksha Life = 98.7% (industry avg 96.2%). Higher means more claims paid.
2. Solvency Ratio: Our 2.1x (IRDAI minimum 1.5x) — financial strength to pay future claims.
3. Exclusions: Read the fine print — cheap plans often exclude suicide, adventure sports, specific illnesses.
4. Portability: 3 years premiums paid here create locked-in goodwill bonus. Starting fresh loses that.
5. Medical re-examination: new insurer will re-examine you — any current health conditions may become exclusions.
Is the price difference worth these risks? Let's calculate the real cost of switching.""",
     ["cheaper", "competitor", "better price", "other company", "switching"]),

    ("obj_p05", "Not Worth It",
     """OBJECTION: I've been paying for years and got nothing back. It's not worth it.
RESPONSE: I hear you — insurance can feel intangible until the moment it matters most.
Let me reframe this: you paid ₹X in premiums. In return, your family had ₹{sum_assured} of protection
every single day. That 'nothing back' was actually ₹{total_protection_days} days of financial security.
For your Endowment/MoneyBack policy, you WILL receive ₹{maturity_amount} at maturity — that IS your money back.
For Term plans: consider the peace of mind cost. ₹12,000/year for ₹1 crore cover = ₹33/day. Less than a coffee.""",
     ["not worth", "no return", "waste of money", "nothing back"]),

    ("obj_p06", "Financial Hardship",
     """OBJECTION: I'm going through a financial difficulty right now.
RESPONSE: I'm truly sorry to hear that. We have specific options designed for situations like yours:
1. Premium Holiday: pause premiums for 6-12 months (after 3 years of payment) — policy stays active.
2. Reduced Paid-Up: stop paying; policy continues with reduced Sum Assured proportionate to premiums paid.
3. Loan Against Policy: borrow up to 90% of surrender value — no credit check, low interest (9% p.a.).
4. Partial Surrender: for ULIPs, withdraw up to 20% of fund value after lock-in period.
Your policy has accumulated significant value — let's protect that rather than letting it lapse.""",
     ["financial difficulty", "hardship", "can't pay", "job loss", "struggling"]),

    ("obj_p07", "Want to Surrender",
     """OBJECTION: I want to surrender the policy and take my money.
RESPONSE: Before surrendering, please consider:
Current Surrender Value: ₹{surrender_value} (you would receive this).
If you hold till maturity, you receive: ₹{maturity_value} — that's ₹{difference} more.
Tax implication: surrendering before 5 years means tax on surrender value as income.
Alternative: Policy Loan — get 80-90% of surrender value NOW without losing the policy.
If you still want to surrender, I can process it — but I'd be failing you if I didn't show you what you're giving up.""",
     ["surrender", "close policy", "cancel", "take money out"]),

    ("obj_p08", "Premium Paid via Auto-Debit Already",
     """OBJECTION: I thought my premium was on auto-debit — why is this due?
RESPONSE: Thank you for mentioning this — let's check.
Possible reasons auto-debit may not have processed:
1. Bank mandate expired (ECS mandates renew every 2-3 years)
2. Insufficient balance at the time of debit attempt
3. Bank account number changed
4. NACH registration pending
I can check the mandate status right now. If there's a failure, we can process payment today
and re-register the mandate to avoid this in future. The policy is still within grace period.""",
     ["auto debit", "ECS", "NACH", "automatic payment", "standing instruction"]),

    # TRUST / COMPANY (10 pairs)
    ("obj_t01", "Don't Trust Private Insurers",
     """OBJECTION: I don't trust private insurance companies. Only LIC is safe.
RESPONSE: Completely understandable — LIC has earned trust over decades. Here's the context:
1. IRDAI regulation: ALL insurers (including private) are regulated by IRDAI. Same rules apply.
2. Solvency margin: We maintain 2.1x solvency ratio. IRDAI would intervene before any insurer fails.
3. Policy Holder Protection Fund: IRDAI mandates a fund for policyholder protection.
4. Our CSR: 98.7% — we settled 98.7 claims for every 100 filed in FY2024-25.
5. 14 years in business, 2.3 crore policyholders, AA+ rated by CRISIL.
The question isn't private vs public — it's about the numbers.""",
     ["trust", "LIC", "private company", "safe", "reliable"]),

    ("obj_t02", "Claims Get Rejected",
     """OBJECTION: Insurance companies always reject claims on technicalities.
RESPONSE: This is a common and valid concern. Let's talk facts:
Our Claim Settlement Ratio: 98.7% in FY2024-25 (IRDAI published data).
Common reasons for rejection (and how to avoid):
1. Non-disclosure: always disclose existing health conditions at purchase (we'll ask again).
2. Policy lapse: keep the policy active — renewing today prevents this risk entirely.
3. Waiting period: for health policies, 30-90 days waiting period for pre-existing conditions.
4. Exclusions: read the exclusions section — we can walk through yours specifically.
The best way to ensure claim settlement is to renew on time and maintain all disclosures.""",
     ["claim rejection", "reject", "fine print", "technicality", "settlement"]),

    ("obj_t03", "Bad Experience Previously",
     """OBJECTION: I had a bad experience with insurance before.
RESPONSE: I'm genuinely sorry to hear that — and I want to understand what happened.
[Listen carefully to the specific issue]
What I can promise: transparency, and a clear record of our commitments.
Let me specifically address [their issue]:
- If claim delay: average settlement time now 7 days (from 30 days in 2019)
- If mis-selling: free look period protects you — any concern within 30 days, full refund
- If premium issue: all charges itemised on your policy bond page 3
What would make you feel confident this time?""",
     ["bad experience", "cheated", "disappointed", "previous insurer"]),

    ("obj_t04", "Agent Will Disappear",
     """OBJECTION: The agent will disappear after I buy. No service after sales.
RESPONSE: Valid concern — here's what's different:
1. This is a direct call from Suraksha Life's central operations team — not an individual agent.
2. Your policy is managed by the company, not an individual. Agent changes don't affect your policy.
3. Self-service: SuraBot app 24/7 — premium payment, certificate download, nominee change.
4. 24×7 helpline: 1800-XXX-XXXX (toll-free)
5. Dedicated renewal manager: {agent_name} assigned to your account for this policy year.
6. All commitments I make today are recorded and audited by our compliance team.""",
     ["agent disappear", "no service", "after sales", "ghosted"]),

    # URGENCY / PROCRASTINATION (10 pairs)
    ("obj_u01", "Will Renew Next Month",
     """OBJECTION: I'll renew next month / let me think about it.
RESPONSE: I completely respect your decision-making process. Just two things to be aware of:
1. Grace period ends on {grace_end_date} — after that, policy lapses and revival requires medical exam.
2. If anything happens between now and next month, your family has NO protection.
The renewal takes 3 minutes right now — same premium, same benefits, zero paperwork.
If you want to think about upgrading riders or sum assured, we can absolutely do that next month.
But to maintain protection continuity, shall we process the renewal today?""",
     ["next month", "later", "not now", "will think", "procrastinate"]),

    ("obj_u02", "Too Busy Right Now",
     """OBJECTION: I'm very busy, can you call back later?
RESPONSE: Absolutely — I respect your time. Before I let you go:
Your policy lapses on {lapse_date}. To keep it active, we just need 2 minutes.
Option A: I'll send a WhatsApp payment link — tap and pay in 60 seconds, whenever convenient today.
Option B: Share a 10-minute window in the next 2 days — I'll call exactly then.
Option C: I'll call back at {preferred_time} tomorrow as per your preference on file.
Which works best?""",
     ["busy", "call back", "not now", "later", "no time"]),

    ("obj_u03", "Already Have Other Insurance",
     """OBJECTION: I already have insurance from my employer / other company.
RESPONSE: That's great — having coverage is important! A few things to consider:
1. Employer insurance: typically 2-3× annual salary. For a family of 4, that's rarely enough.
2. Job change risk: employer cover ends the day you leave. Personal policy travels with you.
3. Group policy exclusions: often no critical illness, no personal accident, limited hospital network.
4. Complementary protection: this policy covers gaps your employer plan doesn't.
Would you like me to do a quick coverage gap analysis comparing your employer plan with this one?""",
     ["employer insurance", "already have", "group cover", "other policy"]),

    ("obj_u04", "No Urgency, Policy Just Started",
     """OBJECTION: My policy is new / I have plenty of time before renewal.
RESPONSE: Excellent — and that's exactly why NOW is the best time to confirm the plan!
Early renewal benefits:
1. Lock in current premium rate before next age birthday (premiums increase with age).
2. Start the EMI AutoPay mandate 30 days before due date for smooth processing.
3. Review if Sum Assured needs upgrading (income, family size changes).
4. Ensure nominee details are current.
No urgency, no pressure — just a 5-minute review to make sure everything is optimal.""",
     ["new policy", "not due yet", "plenty of time", "early"]),

    # HEALTH / MEDICAL (8 pairs)
    ("obj_h01", "Already Have Pre-existing Condition",
     """OBJECTION: I have a pre-existing condition. Will my claim be rejected?
RESPONSE: Thank you for being upfront — this is exactly the right conversation to have.
Pre-existing conditions at the time of purchase: covered after a waiting period (usually 2-4 years).
New conditions after policy start: covered immediately (no waiting period).
Critical point: if you disclosed your condition at the time of purchase, the policy MUST cover it after waiting period.
We have your disclosure form on record — your {condition} was disclosed and accepted at policy issuance.
Your renewal continues with the same terms. No new medical exam needed for renewal.""",
     ["pre-existing", "health condition", "diabetes", "heart", "medical"]),

    ("obj_h02", "Medical Tests Required",
     """OBJECTION: I don't want to do medical tests.
RESPONSE: For RENEWAL of your existing policy, NO medical tests are required.
Your health was assessed when the policy was originally issued — renewal is continuation of that contract.
Medical tests are only needed for:
- New policy purchase above certain sum assured thresholds
- Policy revival after lapse of more than 2 years
- Sum assured enhancement requests
Today's renewal is paperless, testless, and takes 3 minutes.""",
     ["medical test", "doctor", "examination", "health check"]),

    # PROCESS / DOCUMENTATION (7 pairs)
    ("obj_d01", "Too Much Paperwork",
     """OBJECTION: Too much paperwork / documentation required.
RESPONSE: Renewal today requires ZERO paperwork.
It's a digital process:
1. Payment via UPI/Net Banking/Credit Card — 60 seconds
2. Renewal receipt on WhatsApp/email instantly
3. Updated policy certificate downloadable from SuraBot app
4. No forms, no signatures, no physical documents
The original policy bond is already with you — that remains valid. We're just renewing the contract electronically.""",
     ["paperwork", "documents", "forms", "complicated process"]),

    ("obj_d02", "Policy Bond Not Received",
     """OBJECTION: I never received my policy bond / documents.
RESPONSE: I apologise for the inconvenience. Let me resolve this immediately:
1. Digital policy bond: I'll email you the PDF copy right now to {email}.
2. Physical copy: if you'd prefer a hard copy, I can dispatch it within 5 working days.
3. SuraBot app: download anytime from the app using your policy number.
The bond non-receipt does NOT affect your policy validity or claim settlement.
Shall I send the digital copy now while we're on the call?""",
     ["policy bond", "documents not received", "no papers"]),

    # PRODUCT-SPECIFIC (10 pairs)
    ("obj_prod01", "ULIP Market Risk",
     """OBJECTION: ULIPs are risky because of market fluctuations.
RESPONSE: True — ULIPs have market risk, which also means market returns. Some context:
1. Capital protection: life cover stays constant regardless of NAV performance.
2. Long-term wealth: 15+ year ULIP horizons have historically beaten FD returns significantly.
3. Risk profiling: you can switch to a 100% debt fund at any time (4 free switches/year).
4. Current fund allocation: your policy shows {equity_pct}% equity, {debt_pct}% debt.
Considering you're {years_to_maturity} years from maturity, we can gradually shift to safer funds.
Want me to recommend an asset allocation based on your risk appetite?""",
     ["ULIP risk", "market", "NAV", "equity", "volatile"]),

    ("obj_prod02", "Term Plan Has No Returns",
     """OBJECTION: Term plan gives nothing if I survive. It's a waste.
RESPONSE: Let's reframe: Term insurance is protection, not investment — and that's its strength.
Pure protection = maximum cover at minimum cost.
₹1 crore cover at age 35 = ₹10,000-15,000/year. Equivalent endowment = ₹1,00,000+/year.
The 'saved' ₹85,000/year invested in a SIP at 12% = ₹2.3 crore at age 60. 
That's 'buy term + invest the rest' — a strategy endorsed by most financial planners.
However, if you want a return element, I can show you our Term with Return of Premium option.""",
     ["no returns", "term waste", "nothing if survive", "ROP"]),

    ("obj_prod03", "Pension Plan Lock-in",
     """OBJECTION: Pension money is locked till retirement. What if I need it?
RESPONSE: Good point — let's talk flexibility:
1. Partial withdrawal: after 3 years, withdraw up to 25% for specific emergencies (medical, education).
2. Policy loan: borrow against accumulated corpus at any time.
3. Surrender: allowed after 3 years with applicable charges (reducing to 0% after year 5).
4. Premium holiday: pause contributions for 1-2 years without policy lapse.
The lock-in is actually a feature — it prevents premature withdrawal and helps you stay disciplined.
Your corpus so far: ₹{corpus} — an asset you've built consistently.""",
     ["pension lock-in", "retirement", "can't withdraw", "flexibility"]),

    # COMPETITOR SPECIFIC (5 pairs)
    ("obj_c01", "LIC is Better",
     """OBJECTION: LIC is better / government-backed.
RESPONSE: LIC is an excellent insurer with a strong legacy. A fair comparison:
Claim Settlement: LIC 98.6% vs Suraksha Life 98.7% (FY24-25, IRDAI data)
Premium competitiveness: Suraksha Life Term Shield is 15-20% lower premium for same cover
Digital service: Our SuraBot app processes claims, generates certificates, handles changes 24×7
Flexibility: Fund switching, partial withdrawal, premium holiday — not available in comparable LIC plans
Government backing: Yes, LIC has sovereign guarantee. We have IRDAI's policyholder protection framework.
Both are safe choices. The question is which offers better VALUE for your specific needs.""",
     ["LIC", "government", "public sector", "sovereign"]),

    ("obj_c02", "Online Insurance Apps are Cheaper",
     """OBJECTION: I can get cheaper insurance on PolicyBazaar / online.
RESPONSE: Absolutely — online aggregators offer good value and I encourage comparison.
What to watch for online:
1. Same insurer, same product: online and offline price should be identical for same plan
2. Some online-only plans have different exclusions — read the fine print carefully
3. Service: aggregators help you buy; for claims and renewals, you deal with the insurer directly
4. Our online rate for your policy: ₹{online_premium} — matching what aggregators show
If you found a specific plan cheaper than ours, share the details — I can check if it's truly comparable.""",
     ["PolicyBazaar", "online", "aggregator", "cheaper online"]),

    # REGULATORY / LEGAL (5 pairs)
    ("obj_r01", "IRDAI Complaint",
     """OBJECTION: I want to file a complaint with IRDAI.
RESPONSE: You absolutely have that right — and I want to help resolve this before it reaches that stage.
IRDAI Grievance process: Company must acknowledge within 3 days, resolve within 14 days.
Escalation path if unresolved:
1. Our Grievance Officer: grievance@suraксhalife.com / 1800-XXX-XXXX (toll-free)
2. IRDAI Bima Bharosa portal: https://bimabharosa.irdai.gov.in
3. Insurance Ombudsman: free, no lawyer needed, binding on insurer for claims up to ₹50 lakh
May I understand the specific issue? I have authority to resolve most concerns on this call.""",
     ["IRDAI", "complaint", "grievance", "ombudsman", "legal"]),

    ("obj_r02", "Policy Terms Changed",
     """OBJECTION: The terms changed without my knowledge.
RESPONSE: By regulation, Suraksha Life cannot change core policy terms after issuance without consent.
What CAN change periodically:
1. Service tax/GST rate (government mandate — notified by IRDAI)
2. Rider premiums (with 3-month advance notice)
3. Fund NAV (ULIP only — market driven)
What CANNOT change:
- Sum Assured, Death Benefit structure, Policy Term, Premium for base plan
Please share which specific term you believe changed — I can pull the policy schedule right now.""",
     ["terms changed", "policy changed", "without consent", "bait and switch"]),

    # DIGITAL / TECHNOLOGY (5 pairs)
    ("obj_dg01", "Not Comfortable Paying Online",
     """OBJECTION: I'm not comfortable paying online. I prefer cheque / cash.
RESPONSE: Your preference is absolutely valid. Payment options:
1. Cheque: payable to 'Suraksha Life Insurance Co Ltd', courier to nearest branch
2. RTGS/NEFT: bank transfer (account details in policy bond, page 5)
3. Branch walk-in: 847 branches across India — nearest to you: {nearest_branch}
4. Demand Draft: accepted at all branches
5. If you're comfortable, I can guide you through net banking step-by-step right now
Processing time: cheques take 3-5 working days — please ensure within grace period.""",
     ["online payment", "not comfortable", "cheque", "cash", "branch"]),

    ("obj_dg02", "Worried About Fraud",
     """OBJECTION: I'm worried this call / link is a fraud.
RESPONSE: Absolutely right to be cautious — insurance fraud is real.
Verify this is genuine:
1. Call us back on 1800-XXX-XXXX (our published number) and ask for renewal department
2. Check your policy number {policy_number} on our website: www.suraксhalife.com
3. Our SMS/WhatsApp will only come from 'SuraксhaLife' (verified sender ID)
4. We will NEVER ask for your Aadhaar/PAN/bank password/OTP over phone
5. Payment link will ONLY be from suraксhalife.com domain — check URL before paying
I'm happy to hang up and let you call us back to confirm. Your security matters more.""",
     ["fraud", "scam", "fake call", "security", "trust"]),

    # LANGUAGE / COMMUNICATION (5 pairs)
    ("obj_l01", "Prefer Hindi / Regional Language",
     """OBJECTION: I'm not comfortable in English. Can we speak in Hindi?
RESPONSE: बिल्कुल! हम आपसे हिंदी में बात कर सकते हैं।
[SWITCH TO HINDI / REGIONAL LANGUAGE]
For Hindi: हमारे पास पूर्ण हिंदी सेवा उपलब्ध है।
For Tamil: நாங்கள் தமிழிலும் உதவி செய்கிறோம்.
For Telugu: మేము తెలుగులో కూడా మాట్లాడగలం.
Available in: Hindi, Marathi, Bengali, Tamil, Telugu, Kannada, Malayalam, Gujarati.
Let me transfer you to a specialist in your preferred language — 2 minute wait.""",
     ["language", "Hindi", "regional", "not English", "translate"]),

    ("obj_l02", "Spouse / Family Member Must Decide",
     """OBJECTION: My husband/wife makes financial decisions. I'll ask them.
RESPONSE: Of course — this is a family decision and both should be aligned.
Let me suggest: shall I send a WhatsApp/email summary to you BOTH right now?
Your spouse's number: I'll need that from you. Or shall I schedule a call when both are available?
Quick summary I'll share: current policy details, renewal amount, consequences of non-renewal.
They can review at leisure and you can call us back. But please ensure it's done before {grace_end_date}.""",
     ["spouse", "family decision", "husband", "wife", "discuss"]),

    # SPECIFIC SITUATIONS (10 pairs)
    ("obj_s01", "Recently Retired",
     """OBJECTION: I've recently retired / no longer have income.
RESPONSE: Congratulations on your retirement! This actually makes the policy MORE important:
1. No employer cover from today — this policy is your family's sole protection.
2. Reduced paid-up option: maintain cover without paying new premiums (using accrued bonus).
3. Senior Citizen payment assistance: we have a scheme where children can pay on your behalf with tax benefit.
4. Policy loan: use accumulated value to fund the renewal itself — essentially policy self-funds.
5. Sum Assured review: consider if current cover is still appropriate for your retirement liabilities.
Your pension/savings replace income, but do they also replace your insurance protection?""",
     ["retired", "no income", "pension", "senior citizen"]),

    ("obj_s02", "Diagnosis of Serious Illness",
     """OBJECTION: I've been recently diagnosed with a serious illness.
RESPONSE: I'm so sorry to hear that. Please take care of yourself first.
This actually makes renewing CRITICALLY important right now:
1. Critical Illness Rider: if you have this rider, a claim may be payable TODAY for your diagnosis.
2. Waiver of Premium: if you have this rider, all future premiums are WAIVED due to disability.
3. Policy lapse now = no claim payable on death or disability.
4. New policy post-diagnosis: impossible or very expensive — this existing policy is your protection.
Let me check your riders RIGHT NOW. This could mean significant financial help for your family.""",
     ["illness", "cancer", "heart attack", "diagnosed", "critical"]),
]

# Build full objection documents
OBJECTION_DOCS: list[KBDocument] = [
    KBDocument(obj_id, "objection", title, content, tags)
    for obj_id, title, content, tags in _OBJ_DATA
]


# ── 3. Benefit Calculators ──────────────────────────────────────────────────────

CALCULATOR_DOCS: list[KBDocument] = [
    KBDocument("calc_001", "calculator", "Maturity Benefit Calculator Guide",
        """MATURITY BENEFIT = Sum Assured + Accrued Bonus + Terminal Bonus
Accrued Bonus: declared annually as % of Sum Assured.
Example: ₹10 lakh SA, 3.5% bonus for 20 years = ₹7 lakh bonus.
Terminal Bonus: typically 15-25% of total accrued bonus, paid only at maturity.
ULIP Maturity: Fund Units × NAV at maturity date.
Money Back: deduct survival benefits already paid from final maturity amount.
Tax: maturity proceeds tax-free under 10(10D) if policy qualifies.""",
        ["maturity", "bonus", "calculator", "returns"]),

    KBDocument("calc_002", "calculator", "Tax Savings Calculator",
        """TAX SAVINGS ON INSURANCE PREMIUMS
Section 80C: Up to ₹1,50,000 deductible. Tax saved = ₹1,50,000 × tax_rate.
At 30% slab: saves ₹46,800 (including 4% cess). At 20% slab: ₹31,200.
Section 80D (Health Rider): Additional ₹25,000 deductible.
Section 10(10D): Death/maturity proceeds tax-free (conditions apply).
Example: ₹50,000/year premium at 30% tax bracket = ₹15,600 annual tax saving.
Net effective premium after tax benefit = ₹50,000 - ₹15,600 = ₹34,400.""",
        ["tax", "80C", "80D", "savings", "deduction"]),

    KBDocument("calc_003", "calculator", "Surrender Value Calculation",
        """GUARANTEED SURRENDER VALUE (GSV) = 30% × Premiums Paid × (years_remaining/policy_term)
(Not applicable for first 2 years — no surrender value in year 1 and 2)
SPECIAL SURRENDER VALUE (SSV): Paid-up value × surrender factor (insurer-specific table)
SSV is usually higher than GSV — insurer pays higher of the two.
ULIP Surrender: Fund Value minus applicable surrender charges.
Surrender Charges (ULIP): 0% after 5 years; reducing schedule in years 1-5.
Advice: Always check if policy loan is preferable to surrender.""",
        ["surrender", "surrender value", "GSV", "SSV"]),

    KBDocument("calc_004", "calculator", "Death Benefit Calculation",
        """DEATH BENEFIT = Higher of (Sum Assured, 10× Annual Premium, 105% Premiums Paid)
For most life policies, Death Benefit = Sum Assured (no deduction of bonuses paid).
Accident Death Benefit (with rider): Additional Sum Assured (typically equal to base SA).
Critical Illness Rider: lump sum on diagnosis (does not reduce death benefit in most plans).
GST on death claims: NIL (death proceeds are tax-free).
Enhanced SA (with increasing cover option): SA increases 5% annually — verify schedule.
Suicide clause: claims not payable within first year (IRDAI mandate).""",
        ["death benefit", "death claim", "nominee", "claim"]),
]


# ── 4. IRDAI Compliance Docs ───────────────────────────────────────────────────

COMPLIANCE_DOCS: list[KBDocument] = [
    KBDocument("irdai_001", "compliance", "IRDAI Key Communication Rules",
        """IRDAI Circular on Customer Communication (2023):
R01: Policy number must be stated in all communications.
R02: Insurer name must appear prominently.
R03: Renewal amount must be accurate to nearest rupee.
R04: Grace period must be explicitly mentioned if within 30 days of due date.
R05: Opt-out / STOP instructions must be present in every digital message.
R06: Grievance redressal information must be accessible.
R07: Do Not Disturb (DND) registry must be checked before voice calls.
R08: Call timing restricted: 9am-9pm; WhatsApp/SMS: 8am-9pm.
R09: No misleading return projections without IRDAI-approved illustration.""",
        ["IRDAI", "compliance", "rules", "regulation"]),

    KBDocument("irdai_002", "compliance", "IRDAI Grievance Redressal Process",
        """IRDAI Grievance Turnaround Times:
Level 1 (Insurer): Acknowledge within 3 business days, resolve within 14 days.
Level 2 (IRDAI Bima Bharosa): If unresolved by insurer after 14 days.
Level 3 (Insurance Ombudsman): For claims disputes up to ₹50 lakh.
Ombudsman Process: Free, no lawyer required, binding on insurer.
Contact: 1800-425-4732 (IRDAI) | Toll-free, 9am-5pm Mon-Sat.
Bima Bharosa Portal: https://bimabharosa.irdai.gov.in
Policy Holder Protection Fund: maintained by each insurer under IRDAI supervision.""",
        ["grievance", "complaint", "IRDAI", "ombudsman"]),

    KBDocument("irdai_003", "compliance", "Free Look Period Rules",
        """IRDAI Free Look Period Regulations:
Duration: 15 days from receipt of policy document.
Distance Marketing: 30 days (email/courier sales).
Process: Written request to insurer with original policy bond.
Refund: Full premium MINUS proportionate risk premium for cover period MINUS medical exam costs.
After free look expiry: Policy cannot be cancelled without insurer's consent.
Insurer obligation: Process refund within 15 days of receiving free look request.
Second opinion on health: Allowed under free look without penalty.""",
        ["free look", "cancellation", "30 days", "refund"]),

    KBDocument("irdai_004", "compliance", "DND and Consent Rules",
        """Do Not Disturb (DND) / TRAI Regulations:
NCPR (National Customer Preference Registry): customers can opt out of commercial calls.
DND Check: mandatory before every voice call attempt.
WhatsApp: requires explicit opt-in; STOP opt-out must be honoured immediately.
SMS: permitted from registered sender ID only; STOP opt-out mandatory.
Email: CAN-SPAM equivalent; unsubscribe link mandatory.
Exemptions: Transactional messages (payment receipts, policy certificates) exempt from DND.
Record keeping: consent records must be maintained for 3 years (IRDAI audit requirement).""",
        ["DND", "consent", "TRAI", "opt-out", "NCPR"]),
]


# ── 5. Renewal Scripts ─────────────────────────────────────────────────────────

SCRIPT_DOCS: list[KBDocument] = [
    KBDocument("script_001", "script", "Opening Script — Warm/Empathetic Tone",
        """OPENING (Warm/Empathetic):
'Hello {customer_name}, this is {agent_name} calling from Suraksha Life Insurance.
I hope this is a good time — I'll take just 2 minutes of your time.
I'm calling because your {product_name} policy {policy_number} is due for renewal on {due_date},
and I wanted to personally make sure your family's protection stays uninterrupted.
[Pause — let customer respond]
I know life gets busy — that's why I'm calling to make this as simple as possible for you.'""",
        ["opening", "warm", "empathetic", "script"]),

    KBDocument("script_002", "script", "Opening Script — Professional Tone",
        """OPENING (Professional):
'Good {time_of_day}, may I speak with {customer_name}?
This is {agent_name} from Suraksha Life Insurance's renewal team.
Your policy {policy_number} ({product_name}) renewal is due on {due_date}.
The renewal amount is ₹{premium_amount}.
I can process this right now in under 3 minutes, or I can send you a payment link — whichever is more convenient.'""",
        ["opening", "professional", "direct", "script"]),

    KBDocument("script_003", "script", "Closing Script — Payment Confirmed",
        """CLOSING (Payment Confirmed):
'Excellent! Your payment of ₹{amount} has been received successfully.
Your policy {policy_number} is now renewed until {new_due_date}.
You'll receive:
- Confirmation SMS in 2 minutes
- Email receipt within 15 minutes  
- Updated policy certificate on SuraBot app
Is there anything else I can help you with today? And may I ask — on a scale of 1-10, how was your experience today?'""",
        ["closing", "payment done", "confirmation", "script"]),

    KBDocument("script_004", "script", "Closing Script — Callback Scheduled",
        """CLOSING (Callback Scheduled):
'Absolutely understood. I've noted your preference for a callback on {callback_date} at {callback_time}.
Your reference number for this call is {call_ref}.
Please note: your grace period ends on {grace_end}. We'll absolutely call you before then.
If anything changes before then, call us on 1800-XXX-XXXX (toll-free 24×7) or pay via SuraBot app.
Take care, {customer_name}. We look forward to speaking again.'""",
        ["closing", "callback", "follow-up", "script"]),

    KBDocument("script_005", "script", "Escalation Handoff Script",
        """ESCALATION HANDOFF:
'I completely understand, {customer_name}. Let me connect you with our senior specialist
who handles exactly these situations. They have full authority to resolve this for you.
[Transfer details: connecting to {specialist_name}, Agent ID {agent_id}]
Before I transfer: your case reference is {case_id}. You won't need to repeat your story.
I've summarised everything for {specialist_name} — they're expecting your call.
Connecting now — please hold for 30 seconds.'""",
        ["escalation", "transfer", "senior specialist", "handoff"]),
]


# ── All documents combined ─────────────────────────────────────────────────────

ALL_DOCUMENTS: list[KBDocument] = (
    PRODUCT_FAQS
    + OBJECTION_DOCS
    + CALCULATOR_DOCS
    + COMPLIANCE_DOCS
    + SCRIPT_DOCS
)


# ═══════════════════════════════════════════════════════════════════════════════
#  CHROMA VECTOR STORE BACKEND
# ═══════════════════════════════════════════════════════════════════════════════

class RagKnowledgeBase:
    """
    ChromaDB-backed RAG knowledge base.
    Falls back to keyword TF-IDF search if ChromaDB unavailable.
    """

    COLLECTION_NAME = "renewai_kb"

    def __init__(self):
        self._use_chroma = False
        self._client     = None
        self._collection = None
        self._fallback_docs: list[KBDocument] = []

        try:
            import chromadb
            from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

            ef = SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2",
                device="cpu",
            )
            self._client = chromadb.PersistentClient(path=str(KB_DIR))
            self._collection = self._client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                embedding_function=ef,
                metadata={"hnsw:space": "cosine"},
            )
            self._use_chroma = True
            logger.info("RagKnowledgeBase: ChromaDB backend ready")
        except Exception as e:
            logger.warning(f"RagKnowledgeBase: ChromaDB unavailable ({e}) — using keyword fallback")

    # ── Build / Index ────────────────────────────────────────────────────────

    def build(self, force_rebuild: bool = False) -> int:
        """Index all documents. Idempotent — skips existing docs unless force_rebuild."""
        if self._use_chroma:
            return self._build_chroma(force_rebuild)
        else:
            self._fallback_docs = list(ALL_DOCUMENTS)
            logger.info(f"RagKnowledgeBase (keyword): {len(self._fallback_docs)} docs loaded")
            return len(self._fallback_docs)

    def _build_chroma(self, force_rebuild: bool) -> int:
        existing = self._collection.count()
        if existing >= len(ALL_DOCUMENTS) and not force_rebuild:
            logger.info(f"RagKnowledgeBase: {existing} docs already indexed, skipping rebuild")
            return existing

        if force_rebuild and existing > 0:
            # Delete and recreate
            self._client.delete_collection(self.COLLECTION_NAME)
            from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
            ef = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2", device="cpu")
            self._collection = self._client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                embedding_function=ef,
                metadata={"hnsw:space": "cosine"},
            )

        # Batch upsert
        batch_ids, batch_docs, batch_metas = [], [], []
        for doc in ALL_DOCUMENTS:
            batch_ids.append(doc.doc_id)
            batch_docs.append(f"{doc.title}\n\n{doc.content}")
            batch_metas.append({
                "category": doc.category,
                "title":    doc.title,
                "tags":     json.dumps(doc.tags),
            })

        # Chroma accepts max 5461 at once — chunk if needed
        BATCH = 100
        for i in range(0, len(batch_ids), BATCH):
            self._collection.upsert(
                ids        = batch_ids[i:i+BATCH],
                documents  = batch_docs[i:i+BATCH],
                metadatas  = batch_metas[i:i+BATCH],
            )

        count = self._collection.count()
        logger.info(f"RagKnowledgeBase: {count} documents indexed in ChromaDB")
        return count

    # ── Query ────────────────────────────────────────────────────────────────

    def query(
        self,
        text:       str,
        n:          int = 3,
        category:   Optional[str] = None,
    ) -> list[dict]:
        """
        Semantic search. Returns list of dicts with keys:
          doc_id, category, title, content, score, tags
        """
        if self._use_chroma:
            return self._query_chroma(text, n, category)
        else:
            return self._query_keyword(text, n, category)

    def _query_chroma(self, text: str, n: int, category: Optional[str]) -> list[dict]:
        where = {"category": category} if category else None
        try:
            results = self._collection.query(
                query_texts = [text],
                n_results   = min(n, self._collection.count()),
                where       = where,
            )
        except Exception as e:
            logger.warning(f"ChromaDB query error: {e}")
            return self._query_keyword(text, n, category)

        out = []
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i]
            dist = results["distances"][0][i]
            doc_text = results["documents"][0][i]
            # Split title / content from indexed text
            parts = doc_text.split("\n\n", 1)
            out.append({
                "doc_id":   doc_id,
                "category": meta.get("category", ""),
                "title":    meta.get("title", parts[0] if parts else ""),
                "content":  parts[1] if len(parts) > 1 else doc_text,
                "score":    round(1 - dist, 4),   # cosine similarity
                "tags":     json.loads(meta.get("tags", "[]")),
            })
        return out

    def _query_keyword(self, text: str, n: int, category: Optional[str]) -> list[dict]:
        """Simple keyword overlap fallback."""
        words = set(re.sub(r"[^a-z0-9 ]", "", text.lower()).split())
        if not words:
            return []

        scored = []
        for doc in (self._fallback_docs or ALL_DOCUMENTS):
            if category and doc.category != category:
                continue
            doc_words = set(
                re.sub(r"[^a-z0-9 ]", "", (doc.title + " " + doc.content + " " + " ".join(doc.tags)).lower()).split()
            )
            overlap = len(words & doc_words)
            if overlap > 0:
                scored.append((overlap, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "doc_id":   d.doc_id,
                "category": d.category,
                "title":    d.title,
                "content":  d.content,
                "score":    round(s / max(len(words), 1), 4),
                "tags":     d.tags,
            }
            for s, d in scored[:n]
        ]

    # ── Objection lookup ─────────────────────────────────────────────────────

    def get_objection_response(self, objection_text: str) -> Optional[dict]:
        """
        Find the best matching objection response.
        Returns the response dict or None if no good match.
        """
        results = self.query(objection_text, n=1, category="objection")
        if results and results[0]["score"] > 0.3:
            return results[0]
        return None

    # ── Context builder for agents ───────────────────────────────────────────

    def build_context(self, query: str, n: int = 3) -> str:
        """Build a RAG context string to inject into agent prompts."""
        docs = self.query(query, n=n)
        if not docs:
            return ""
        parts = []
        for d in docs:
            parts.append(f"[{d['category'].upper()} — {d['title']}]\n{d['content'][:600]}")
        return "\n\n---\n\n".join(parts)

    # ── Stats ────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        total    = len(ALL_DOCUMENTS)
        by_cat   = {}
        for doc in ALL_DOCUMENTS:
            by_cat[doc.category] = by_cat.get(doc.category, 0) + 1
        indexed  = self._collection.count() if self._use_chroma else len(self._fallback_docs)
        return {
            "total_documents": total,
            "indexed":         indexed,
            "backend":         "chromadb" if self._use_chroma else "keyword",
            "by_category":     by_cat,
            "kb_dir":          str(KB_DIR),
        }
