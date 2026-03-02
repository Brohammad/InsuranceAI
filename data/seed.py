"""
data/seed.py
────────────
Seeds the SQLite database with realistic mock data
based on Suraksha Life Insurance case study numbers.

Includes 20 customers covering all segments, product types,
languages, and risk profiles described in chatpwc.txt.

Run:  python data/seed.py
"""

import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

# ── Make sure project root is on PYTHONPATH ───────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.database import init_db, upsert_customer, upsert_policy
from core.models import (
    Channel, Customer, Language, Policy, PolicyStatus, ProductType
)
from rich.console import Console
from rich.table import Table

console = Console()

TODAY = date.today()


def make_due(days_from_now: int) -> date:
    return TODAY + timedelta(days=days_from_now)


def make_start(years_ago: int) -> date:
    return date(TODAY.year - years_ago, TODAY.month, TODAY.day)


# ═══════════════════════════════════════════════════════════════════════════════
#  CUSTOMERS  (20 profiles — every segment, product, language covered)
# ═══════════════════════════════════════════════════════════════════════════════

CUSTOMERS = [

    # ── 1. Rajesh Kumar — Term, WhatsApp-first, Hindi, Nudge Needed ──────────
    Customer(
        customer_id="C001",
        name="Rajesh Kumar",
        age=42,
        gender="M",
        city="Mumbai",
        state="Maharashtra",
        preferred_language=Language.HINDI,
        preferred_channel=Channel.WHATSAPP,
        preferred_call_time="18:00-21:00",
        email="rajesh.kumar@email.com",
        phone="+919876543001",
        whatsapp_number="+919876543001",
        occupation="IT Professional",
        is_on_dnd=False,
    ),

    # ── 2. Meenakshi Sharma — Endowment, Distress flag, Hindi ────────────────
    Customer(
        customer_id="C002",
        name="Meenakshi Sharma",
        age=58,
        gender="F",
        city="Pune",
        state="Maharashtra",
        preferred_language=Language.MARATHI,
        preferred_channel=Channel.WHATSAPP,
        preferred_call_time="10:00-13:00",
        email="meenakshi.sharma@email.com",
        phone="+919876543002",
        whatsapp_number="+919876543002",
        occupation="Homemaker",
        is_on_dnd=False,
    ),

    # ── 3. Vikram Nair — ULIP, Email-first, English, Wealth Builder ──────────
    Customer(
        customer_id="C003",
        name="Vikram Nair",
        age=35,
        gender="M",
        city="Bengaluru",
        state="Karnataka",
        preferred_language=Language.ENGLISH,
        preferred_channel=Channel.EMAIL,
        preferred_call_time="09:00-10:00",
        email="vikram.nair@techcorp.com",
        phone="+919876543003",
        whatsapp_number="+919876543003",
        occupation="Software Engineer",
        is_on_dnd=False,
    ),

    # ── 4. Priya Pillai — Term, Malayalam, Voice-first, High Risk ────────────
    Customer(
        customer_id="C004",
        name="Priya Pillai",
        age=38,
        gender="F",
        city="Kochi",
        state="Kerala",
        preferred_language=Language.MALAYALAM,
        preferred_channel=Channel.VOICE,
        preferred_call_time="19:00-21:00",
        email="priya.pillai@email.com",
        phone="+919876543004",
        whatsapp_number="+919876543004",
        occupation="Nurse",
        is_on_dnd=False,
    ),

    # ── 5. Arjun Mehta — Money Back, Gujarati, Price Sensitive ───────────────
    Customer(
        customer_id="C005",
        name="Arjun Mehta",
        age=45,
        gender="M",
        city="Ahmedabad",
        state="Gujarat",
        preferred_language=Language.GUJARATI,
        preferred_channel=Channel.WHATSAPP,
        preferred_call_time="20:00-21:00",
        email="arjun.mehta@email.com",
        phone="+919876543005",
        whatsapp_number="+919876543005",
        occupation="Shopkeeper",
        is_on_dnd=False,
    ),

    # ── 6. Lakshmi Rajan — Term, Tamil, Voice, Auto Renewer ──────────────────
    Customer(
        customer_id="C006",
        name="Lakshmi Rajan",
        age=52,
        gender="F",
        city="Chennai",
        state="Tamil Nadu",
        preferred_language=Language.TAMIL,
        preferred_channel=Channel.VOICE,
        preferred_call_time="09:00-11:00",
        email="lakshmi.rajan@email.com",
        phone="+919876543006",
        whatsapp_number="+919876543006",
        occupation="School Teacher",
        is_on_dnd=False,
    ),

    # ── 7. Suresh Reddy — Pension, Telugu, Email, Wealth Builder ─────────────
    Customer(
        customer_id="C007",
        name="Suresh Reddy",
        age=48,
        gender="M",
        city="Hyderabad",
        state="Telangana",
        preferred_language=Language.TELUGU,
        preferred_channel=Channel.EMAIL,
        preferred_call_time="18:00-20:00",
        email="suresh.reddy@business.com",
        phone="+919876543007",
        whatsapp_number="+919876543007",
        occupation="Business Owner",
        is_on_dnd=False,
    ),

    # ── 8. Ananya Das — Endowment, Bengali, WhatsApp, Nudge Needed ───────────
    Customer(
        customer_id="C008",
        name="Ananya Das",
        age=31,
        gender="F",
        city="Kolkata",
        state="West Bengal",
        preferred_language=Language.BENGALI,
        preferred_channel=Channel.WHATSAPP,
        preferred_call_time="20:00-22:00",
        email="ananya.das@email.com",
        phone="+919876543008",
        whatsapp_number="+919876543008",
        occupation="Government Employee",
        is_on_dnd=False,
    ),

    # ── 9. Mohammed Iqbal — ULIP, Hindi, Voice, High Risk ────────────────────
    Customer(
        customer_id="C009",
        name="Mohammed Iqbal",
        age=40,
        gender="M",
        city="Lucknow",
        state="Uttar Pradesh",
        preferred_language=Language.HINDI,
        preferred_channel=Channel.VOICE,
        preferred_call_time="19:00-21:00",
        email="iqbal.m@email.com",
        phone="+919876543009",
        whatsapp_number="+919876543009",
        occupation="Taxi Driver",
        is_on_dnd=False,
    ),

    # ── 10. Deepa Krishnan — Health Rider, Kannada, Email ────────────────────
    Customer(
        customer_id="C010",
        name="Deepa Krishnan",
        age=36,
        gender="F",
        city="Mysuru",
        state="Karnataka",
        preferred_language=Language.KANNADA,
        preferred_channel=Channel.EMAIL,
        preferred_call_time="09:00-10:00",
        email="deepa.k@email.com",
        phone="+919876543010",
        whatsapp_number="+919876543010",
        occupation="Doctor",
        is_on_dnd=False,
    ),

    # ── 11. Ramesh Patil — Term, Marathi, Voice, Price Sensitive ─────────────
    Customer(
        customer_id="C011",
        name="Ramesh Patil",
        age=55,
        gender="M",
        city="Nagpur",
        state="Maharashtra",
        preferred_language=Language.MARATHI,
        preferred_channel=Channel.VOICE,
        preferred_call_time="17:00-19:00",
        email="ramesh.patil@email.com",
        phone="+919876543011",
        whatsapp_number="+919876543011",
        occupation="Farmer",
        is_on_dnd=False,
    ),

    # ── 12. Kavitha Sundaram — Money Back, Tamil, WhatsApp, Auto Renewer ─────
    Customer(
        customer_id="C012",
        name="Kavitha Sundaram",
        age=43,
        gender="F",
        city="Coimbatore",
        state="Tamil Nadu",
        preferred_language=Language.TAMIL,
        preferred_channel=Channel.WHATSAPP,
        preferred_call_time="20:00-21:30",
        email="kavitha.s@email.com",
        phone="+919876543012",
        whatsapp_number="+919876543012",
        occupation="Textile Business",
        is_on_dnd=False,
    ),

    # ── 13. Sanjay Gupta — Endowment, Hindi, Email, Wealth Builder ───────────
    Customer(
        customer_id="C013",
        name="Sanjay Gupta",
        age=50,
        gender="M",
        city="Delhi",
        state="Delhi",
        preferred_language=Language.HINDI,
        preferred_channel=Channel.EMAIL,
        preferred_call_time="08:00-09:00",
        email="sanjay.gupta@corp.com",
        phone="+919876543013",
        whatsapp_number="+919876543013",
        occupation="CA / Chartered Accountant",
        is_on_dnd=False,
    ),

    # ── 14. Fatima Khan — Term, Hindi, WhatsApp, High Risk ───────────────────
    Customer(
        customer_id="C014",
        name="Fatima Khan",
        age=29,
        gender="F",
        city="Jaipur",
        state="Rajasthan",
        preferred_language=Language.HINDI,
        preferred_channel=Channel.WHATSAPP,
        preferred_call_time="21:00-22:00",
        email="fatima.khan@email.com",
        phone="+919876543014",
        whatsapp_number="+919876543014",
        occupation="Home Baker",
        is_on_dnd=False,
    ),

    # ── 15. Harish Iyer — ULIP, Tamil, Email, Nudge Needed ───────────────────
    Customer(
        customer_id="C015",
        name="Harish Iyer",
        age=33,
        gender="M",
        city="Chennai",
        state="Tamil Nadu",
        preferred_language=Language.TAMIL,
        preferred_channel=Channel.EMAIL,
        preferred_call_time="07:30-09:00",
        email="harish.iyer@startup.io",
        phone="+919876543015",
        whatsapp_number="+919876543015",
        occupation="Startup Founder",
        is_on_dnd=False,
    ),

    # ── 16. Geeta Joshi — Pension, Hindi, Voice, Auto Renewer ────────────────
    Customer(
        customer_id="C016",
        name="Geeta Joshi",
        age=60,
        gender="F",
        city="Varanasi",
        state="Uttar Pradesh",
        preferred_language=Language.HINDI,
        preferred_channel=Channel.VOICE,
        preferred_call_time="10:00-12:00",
        email="geeta.joshi@email.com",
        phone="+919876543016",
        whatsapp_number="+919876543016",
        occupation="Retired Teacher",
        is_on_dnd=False,
    ),

    # ── 17. Nikhil Bose — Endowment, Bengali, Email, Price Sensitive ─────────
    Customer(
        customer_id="C017",
        name="Nikhil Bose",
        age=27,
        gender="M",
        city="Kolkata",
        state="West Bengal",
        preferred_language=Language.BENGALI,
        preferred_channel=Channel.EMAIL,
        preferred_call_time="18:00-20:00",
        email="nikhil.bose@email.com",
        phone="+919876543017",
        whatsapp_number="+919876543017",
        occupation="Junior Engineer",
        is_on_dnd=False,
    ),

    # ── 18. Rekha Nambiar — Health, Malayalam, WhatsApp, High Risk ───────────
    Customer(
        customer_id="C018",
        name="Rekha Nambiar",
        age=47,
        gender="F",
        city="Thiruvananthapuram",
        state="Kerala",
        preferred_language=Language.MALAYALAM,
        preferred_channel=Channel.WHATSAPP,
        preferred_call_time="19:00-21:00",
        email="rekha.n@email.com",
        phone="+919876543018",
        whatsapp_number="+919876543018",
        occupation="Self Employed",
        is_on_dnd=False,
    ),

    # ── 19. Anil Verma — Term, Hindi, WhatsApp, Distress ─────────────────────
    Customer(
        customer_id="C019",
        name="Anil Verma",
        age=44,
        gender="M",
        city="Bhopal",
        state="Madhya Pradesh",
        preferred_language=Language.HINDI,
        preferred_channel=Channel.WHATSAPP,
        preferred_call_time="20:00-22:00",
        email="anil.verma@email.com",
        phone="+919876543019",
        whatsapp_number="+919876543019",
        occupation="Daily Wage Worker",
        is_on_dnd=False,
    ),

    # ── 20. Pooja Shah — ULIP, Gujarati, Email, Wealth Builder ───────────────
    Customer(
        customer_id="C020",
        name="Pooja Shah",
        age=37,
        gender="F",
        city="Surat",
        state="Gujarat",
        preferred_language=Language.GUJARATI,
        preferred_channel=Channel.EMAIL,
        preferred_call_time="08:00-09:30",
        email="pooja.shah@diamondtrade.com",
        phone="+919876543020",
        whatsapp_number="+919876543020",
        occupation="Diamond Trader",
        is_on_dnd=False,
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  POLICIES  (one or more per customer — various risk profiles)
# ═══════════════════════════════════════════════════════════════════════════════

POLICIES = [

    # C001 — Rajesh: Term, due in 13 days, history: 2 on-time, 1 late (Nudge Needed)
    Policy(
        policy_number="SLI-2298741",
        customer_id="C001",
        product_type=ProductType.TERM,
        product_name="Term Shield",
        sum_assured=10_000_000,          # ₹1 Cr
        annual_premium=24_000,
        policy_start_date=make_start(3),
        renewal_due_date=make_due(13),
        tenure_years=20,
        years_completed=3,
        payment_history=["on_time", "on_time", "late"],
    ),

    # C002 — Meenakshi: Endowment, due in 10 days, 8 on-time (Distress scenario)
    Policy(
        policy_number="SLI-1145892",
        customer_id="C002",
        product_type=ProductType.ENDOWMENT,
        product_name="Suraksha Endowment Plus",
        sum_assured=500_000,             # ₹5 L
        annual_premium=18_000,
        policy_start_date=make_start(8),
        renewal_due_date=make_due(10),
        tenure_years=15,
        years_completed=8,
        payment_history=["on_time"] * 8,
    ),

    # C003 — Vikram: ULIP, due in 45 days, 4 on-time (Wealth Builder)
    Policy(
        policy_number="SLI-3302156",
        customer_id="C003",
        product_type=ProductType.ULIP,
        product_name="Suraksha Wealth ULIP",
        sum_assured=2_000_000,           # ₹20 L
        annual_premium=100_000,          # ₹1 L
        policy_start_date=make_start(4),
        renewal_due_date=make_due(45),
        tenure_years=15,
        years_completed=4,
        payment_history=["on_time"] * 4,
    ),

    # C004 — Priya: Term, due in 7 days, 2 on-time 1 missed (High Risk)
    Policy(
        policy_number="SLI-4415037",
        customer_id="C004",
        product_type=ProductType.TERM,
        product_name="Term Shield",
        sum_assured=5_000_000,
        annual_premium=15_000,
        policy_start_date=make_start(3),
        renewal_due_date=make_due(7),
        tenure_years=20,
        years_completed=3,
        payment_history=["on_time", "on_time", "missed"],
    ),

    # C005 — Arjun: Money Back, due in 20 days, 2 late (Price Sensitive)
    Policy(
        policy_number="SLI-5520348",
        customer_id="C005",
        product_type=ProductType.MONEY_BACK,
        product_name="Suraksha MoneyBack 20",
        sum_assured=300_000,
        annual_premium=22_000,
        policy_start_date=make_start(2),
        renewal_due_date=make_due(20),
        tenure_years=20,
        years_completed=2,
        payment_history=["on_time", "late"],
    ),

    # C006 — Lakshmi: Term, due in 30 days, auto-debit, always on-time (Auto Renewer)
    Policy(
        policy_number="SLI-6631459",
        customer_id="C006",
        product_type=ProductType.TERM,
        product_name="Term Shield",
        sum_assured=3_000_000,
        annual_premium=12_000,
        policy_start_date=make_start(5),
        renewal_due_date=make_due(30),
        tenure_years=20,
        years_completed=5,
        payment_history=["on_time"] * 5,
        has_auto_debit=True,
    ),

    # C007 — Suresh: Pension, due in 35 days, 4 on-time (Wealth Builder)
    Policy(
        policy_number="SLI-7742560",
        customer_id="C007",
        product_type=ProductType.PENSION,
        product_name="Suraksha Pension Gold",
        sum_assured=0,
        annual_premium=150_000,          # ₹1.5 L
        policy_start_date=make_start(4),
        renewal_due_date=make_due(35),
        tenure_years=20,
        years_completed=4,
        payment_history=["on_time"] * 4,
    ),

    # C008 — Ananya: Endowment, due in 15 days, 1 late (Nudge Needed)
    Policy(
        policy_number="SLI-8853671",
        customer_id="C008",
        product_type=ProductType.ENDOWMENT,
        product_name="Suraksha Endowment Plus",
        sum_assured=400_000,
        annual_premium=16_000,
        policy_start_date=make_start(2),
        renewal_due_date=make_due(15),
        tenure_years=15,
        years_completed=2,
        payment_history=["on_time", "late"],
    ),

    # C009 — Mohammed: ULIP, due in 5 days, 2 missed (High Risk)
    Policy(
        policy_number="SLI-9964782",
        customer_id="C009",
        product_type=ProductType.ULIP,
        product_name="Suraksha Wealth ULIP",
        sum_assured=1_000_000,
        annual_premium=36_000,
        policy_start_date=make_start(3),
        renewal_due_date=make_due(5),
        tenure_years=15,
        years_completed=3,
        payment_history=["on_time", "missed", "missed"],
    ),

    # C010 — Deepa: Health, due in 22 days, all on-time (Auto Renewer)
    Policy(
        policy_number="SLI-1075893",
        customer_id="C010",
        product_type=ProductType.HEALTH,
        product_name="Suraksha Health Rider Plus",
        sum_assured=500_000,
        annual_premium=8_500,
        policy_start_date=make_start(4),
        renewal_due_date=make_due(22),
        tenure_years=10,
        years_completed=4,
        payment_history=["on_time"] * 4,
        has_auto_debit=True,
    ),

    # C011 — Ramesh: Term, due in 8 days, 3 late (Price Sensitive)
    Policy(
        policy_number="SLI-1186904",
        customer_id="C011",
        product_type=ProductType.TERM,
        product_name="Term Shield",
        sum_assured=2_000_000,
        annual_premium=9_500,
        policy_start_date=make_start(3),
        renewal_due_date=make_due(8),
        tenure_years=20,
        years_completed=3,
        payment_history=["late", "late", "late"],
    ),

    # C012 — Kavitha: Money Back, due in 40 days, auto-debit (Auto Renewer)
    Policy(
        policy_number="SLI-1297015",
        customer_id="C012",
        product_type=ProductType.MONEY_BACK,
        product_name="Suraksha MoneyBack 20",
        sum_assured=600_000,
        annual_premium=28_000,
        policy_start_date=make_start(6),
        renewal_due_date=make_due(40),
        tenure_years=20,
        years_completed=6,
        payment_history=["on_time"] * 6,
        has_auto_debit=True,
    ),

    # C013 — Sanjay: Endowment, due in 25 days, 5 on-time (Wealth Builder)
    Policy(
        policy_number="SLI-1308126",
        customer_id="C013",
        product_type=ProductType.ENDOWMENT,
        product_name="Suraksha Endowment Plus",
        sum_assured=2_000_000,
        annual_premium=75_000,           # ₹75k
        policy_start_date=make_start(5),
        renewal_due_date=make_due(25),
        tenure_years=20,
        years_completed=5,
        payment_history=["on_time"] * 5,
    ),

    # C014 — Fatima: Term, due in 3 days (URGENT), 1 on-time 2 missed (High Risk)
    Policy(
        policy_number="SLI-1419237",
        customer_id="C014",
        product_type=ProductType.TERM,
        product_name="Term Shield",
        sum_assured=2_500_000,
        annual_premium=11_000,
        policy_start_date=make_start(3),
        renewal_due_date=make_due(3),
        tenure_years=20,
        years_completed=3,
        payment_history=["on_time", "missed", "missed"],
    ),

    # C015 — Harish: ULIP, due in 18 days, 1 late (Nudge Needed)
    Policy(
        policy_number="SLI-1520348",
        customer_id="C015",
        product_type=ProductType.ULIP,
        product_name="Suraksha Wealth ULIP",
        sum_assured=1_500_000,
        annual_premium=50_000,
        policy_start_date=make_start(2),
        renewal_due_date=make_due(18),
        tenure_years=15,
        years_completed=2,
        payment_history=["on_time", "late"],
    ),

    # C016 — Geeta: Pension, due in 45 days, 10 on-time, auto-debit (Auto Renewer)
    Policy(
        policy_number="SLI-1631459",
        customer_id="C016",
        product_type=ProductType.PENSION,
        product_name="Suraksha Pension Gold",
        sum_assured=0,
        annual_premium=30_000,
        policy_start_date=make_start(10),
        renewal_due_date=make_due(45),
        tenure_years=20,
        years_completed=10,
        payment_history=["on_time"] * 10,
        has_auto_debit=True,
    ),

    # C017 — Nikhil: Endowment, due in 12 days, 1 missed (Price Sensitive)
    Policy(
        policy_number="SLI-1742560",
        customer_id="C017",
        product_type=ProductType.ENDOWMENT,
        product_name="Suraksha Endowment Plus",
        sum_assured=300_000,
        annual_premium=13_500,
        policy_start_date=make_start(2),
        renewal_due_date=make_due(12),
        tenure_years=15,
        years_completed=2,
        payment_history=["on_time", "missed"],
    ),

    # C018 — Rekha: Health, due in 6 days, 1 on-time 2 missed (High Risk)
    Policy(
        policy_number="SLI-1853671",
        customer_id="C018",
        product_type=ProductType.HEALTH,
        product_name="Suraksha Health Rider Plus",
        sum_assured=500_000,
        annual_premium=9_200,
        policy_start_date=make_start(3),
        renewal_due_date=make_due(6),
        tenure_years=10,
        years_completed=3,
        payment_history=["on_time", "missed", "missed"],
    ),

    # C019 — Anil: Term, due in 14 days, all missed (Distress scenario)
    Policy(
        policy_number="SLI-1964782",
        customer_id="C019",
        product_type=ProductType.TERM,
        product_name="Term Shield",
        sum_assured=3_000_000,
        annual_premium=14_000,
        policy_start_date=make_start(3),
        renewal_due_date=make_due(14),
        tenure_years=20,
        years_completed=3,
        payment_history=["on_time", "missed", "missed"],
    ),

    # C020 — Pooja: ULIP, due in 38 days, 5 on-time (Wealth Builder, HNI)
    Policy(
        policy_number="SLI-2075893",
        customer_id="C020",
        product_type=ProductType.ULIP,
        product_name="Suraksha Wealth ULIP",
        sum_assured=5_000_000,
        annual_premium=200_000,          # ₹2 L — HNI policy
        policy_start_date=make_start(5),
        renewal_due_date=make_due(38),
        tenure_years=15,
        years_completed=5,
        payment_history=["on_time"] * 5,
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  SEED FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def seed():
    console.print("\n[bold cyan]═══ RenewAI Database Seeder ═══[/bold cyan]\n")

    # Init schema
    init_db()
    console.print("[green]✓ Schema created[/green]")

    # Insert customers
    for c in CUSTOMERS:
        upsert_customer(c)
    console.print(f"[green]✓ {len(CUSTOMERS)} customers inserted[/green]")

    # Insert policies
    for p in POLICIES:
        upsert_policy(p)
    console.print(f"[green]✓ {len(POLICIES)} policies inserted[/green]")

    # Summary table
    table = Table(title="\nSeeded Policies", show_header=True)
    table.add_column("Policy No.", style="cyan")
    table.add_column("Customer", style="white")
    table.add_column("Product", style="yellow")
    table.add_column("Premium", style="green")
    table.add_column("Due In", style="magenta")
    table.add_column("Risk", style="red")

    risk_map = {
        "SLI-2298741": "Medium",  "SLI-1145892": "Distress",
        "SLI-3302156": "Low",     "SLI-4415037": "High",
        "SLI-5520348": "Medium",  "SLI-6631459": "Auto",
        "SLI-7742560": "Low",     "SLI-8853671": "Medium",
        "SLI-9964782": "High",    "SLI-1075893": "Auto",
        "SLI-1186904": "Medium",  "SLI-1297015": "Auto",
        "SLI-1308126": "Low",     "SLI-1419237": "High",
        "SLI-1520348": "Medium",  "SLI-1631459": "Auto",
        "SLI-1742560": "Medium",  "SLI-1853671": "High",
        "SLI-1964782": "Distress","SLI-2075893": "Low",
    }

    cust_map = {c.customer_id: c.name for c in CUSTOMERS}

    for p in POLICIES:
        days = (p.renewal_due_date - TODAY).days
        table.add_row(
            p.policy_number,
            cust_map[p.customer_id],
            p.product_type.value.upper(),
            f"₹{p.annual_premium:,.0f}",
            f"{days} days",
            risk_map.get(p.policy_number, "?"),
        )

    console.print(table)
    console.print("\n[bold green]✅ Database seeded successfully![/bold green]\n")


if __name__ == "__main__":
    seed()
