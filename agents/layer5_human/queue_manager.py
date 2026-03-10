"""
agents/layer5_human/queue_manager.py
──────────────────────────────────────
Human Escalation Queue Manager

Manages the queue of EscalationCases that require human agent attention.

Responsibilities:
  1. Load all open escalations from DB (status != resolved)
  2. Priority sorting: P1_URGENT → P2_HIGH → P3_NORMAL → P4_LOW
  3. Agent assignment (round-robin from available agents list)
  4. SLA tracking: P1 = 1h, P2 = 4h, P3 = 24h, P4 = 72h
  5. Resolution recording: close case + update journey
  6. Escalation aging: flag cases breaching SLA
  7. Brief generation: Gemini-powered (or mock) case brief for agent

The queue is backed by the escalation_cases table in DB.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from loguru import logger
from google import genai

from core.config import settings
from core.models import EscalationCase, EscalationPriority, EscalationReason


# ── SLA definitions ───────────────────────────────────────────────────────────

SLA_HOURS: dict[str, int] = {
    EscalationPriority.P1_URGENT.value: 1,
    EscalationPriority.P2_HIGH.value:   4,
    EscalationPriority.P3_NORMAL.value: 24,
    EscalationPriority.P4_LOW.value:    72,
}

PRIORITY_ORDER = {
    EscalationPriority.P1_URGENT.value: 0,
    EscalationPriority.P2_HIGH.value:   1,
    EscalationPriority.P3_NORMAL.value: 2,
    EscalationPriority.P4_LOW.value:    3,
}

# ── Specialist taxonomy ────────────────────────────────────────────────────────
# 20 specialists across 6 teams, each tagged with skills for routing

SPECIALIST_TEAMS = {
    "renewal":    "Renewal & Retention",
    "claims":     "Claims Support",
    "compliance": "Compliance & Grievance",
    "tech":       "Technical & Payments",
    "wellness":   "Customer Wellness",
    "senior":     "Senior / Escalation",
}

# Skills used for routing:
#   distress         — financial/emotional hardship cases
#   mis_selling      — regulatory complaints, proposal doc review
#   bereavement      — bereavement, compassionate cases
#   complaint        — formal grievance, IRDAI escalation
#   requested_human  — general human-assist, onboarding
#   payment_query    — UPI/payment failure, mandate setup
#   medical_query    — health-related product queries
#   legal            — legal notice, court summons
#   nri              — NRI / overseas customer
#   senior_citizen   — 60+ customers needing slow-paced support
#   high_value       — premium > ₹1 lakh, VIP treatment
#   upsell           — cross-sell / upgrade opportunity

MOCK_AGENTS: list[dict] = [
    # ── Team: Renewal & Retention (5 agents) ──────────────────────────────
    {
        "id": "AGT-001", "name": "Ravi Sharma",
        "team": "renewal", "team_name": "Renewal & Retention",
        "skills": ["requested_human", "payment_query", "upsell"],
        "languages": ["hi", "en"],
        "available": True,  "load": 0, "max_load": 5,
        "seniority": "senior",
    },
    {
        "id": "AGT-002", "name": "Sunita Pillai",
        "team": "renewal", "team_name": "Renewal & Retention",
        "skills": ["requested_human", "upsell", "nri"],
        "languages": ["en", "ml", "ta"],
        "available": True,  "load": 1, "max_load": 5,
        "seniority": "mid",
    },
    {
        "id": "AGT-003", "name": "Amit Desai",
        "team": "renewal", "team_name": "Renewal & Retention",
        "skills": ["requested_human", "upsell", "high_value"],
        "languages": ["gu", "hi", "en"],
        "available": False, "load": 3, "max_load": 5,
        "seniority": "mid",
    },
    {
        "id": "AGT-004", "name": "Meena Verma",
        "team": "renewal", "team_name": "Renewal & Retention",
        "skills": ["requested_human", "payment_query", "senior_citizen"],
        "languages": ["hi", "en"],
        "available": True,  "load": 0, "max_load": 5,
        "seniority": "junior",
    },
    {
        "id": "AGT-005", "name": "Karthik Subramanian",
        "team": "renewal", "team_name": "Renewal & Retention",
        "skills": ["requested_human", "upsell", "high_value"],
        "languages": ["ta", "en", "te"],
        "available": True,  "load": 2, "max_load": 5,
        "seniority": "mid",
    },

    # ── Team: Claims Support (4 agents) ───────────────────────────────────
    {
        "id": "AGT-006", "name": "Priya Nair",
        "team": "claims", "team_name": "Claims Support",
        "skills": ["complaint", "mis_selling", "medical_query"],
        "languages": ["ml", "en", "hi"],
        "available": True,  "load": 1, "max_load": 4,
        "seniority": "senior",
    },
    {
        "id": "AGT-007", "name": "Deepak Joshi",
        "team": "claims", "team_name": "Claims Support",
        "skills": ["complaint", "bereavement", "medical_query"],
        "languages": ["hi", "en"],
        "available": True,  "load": 0, "max_load": 4,
        "seniority": "senior",
    },
    {
        "id": "AGT-008", "name": "Lakshmi Rao",
        "team": "claims", "team_name": "Claims Support",
        "skills": ["complaint", "medical_query", "senior_citizen"],
        "languages": ["te", "kn", "en"],
        "available": False, "load": 4, "max_load": 4,
        "seniority": "mid",
    },
    {
        "id": "AGT-009", "name": "Farhan Shaikh",
        "team": "claims", "team_name": "Claims Support",
        "skills": ["complaint", "bereavement", "nri"],
        "languages": ["en", "hi", "ur"],
        "available": True,  "load": 0, "max_load": 4,
        "seniority": "mid",
    },

    # ── Team: Compliance & Grievance (3 agents) ───────────────────────────
    {
        "id": "AGT-010", "name": "Neha Kulkarni",
        "team": "compliance", "team_name": "Compliance & Grievance",
        "skills": ["mis_selling", "complaint", "legal"],
        "languages": ["mr", "hi", "en"],
        "available": True,  "load": 0, "max_load": 3,
        "seniority": "senior",
    },
    {
        "id": "AGT-011", "name": "Sanjay Iyer",
        "team": "compliance", "team_name": "Compliance & Grievance",
        "skills": ["mis_selling", "legal", "high_value"],
        "languages": ["ta", "en", "hi"],
        "available": True,  "load": 1, "max_load": 3,
        "seniority": "senior",
    },
    {
        "id": "AGT-012", "name": "Ananya Bose",
        "team": "compliance", "team_name": "Compliance & Grievance",
        "skills": ["complaint", "mis_selling", "nri"],
        "languages": ["bn", "en", "hi"],
        "available": True,  "load": 0, "max_load": 3,
        "seniority": "mid",
    },

    # ── Team: Technical & Payments (3 agents) ─────────────────────────────
    {
        "id": "AGT-013", "name": "Vikram Patel",
        "team": "tech", "team_name": "Technical & Payments",
        "skills": ["payment_query", "requested_human"],
        "languages": ["gu", "hi", "en"],
        "available": True,  "load": 0, "max_load": 6,
        "seniority": "senior",
    },
    {
        "id": "AGT-014", "name": "Divya Krishnan",
        "team": "tech", "team_name": "Technical & Payments",
        "skills": ["payment_query", "upsell"],
        "languages": ["ta", "en", "kn"],
        "available": True,  "load": 2, "max_load": 6,
        "seniority": "mid",
    },
    {
        "id": "AGT-015", "name": "Rahul Mehta",
        "team": "tech", "team_name": "Technical & Payments",
        "skills": ["payment_query", "nri"],
        "languages": ["en", "hi"],
        "available": False, "load": 5, "max_load": 6,
        "seniority": "junior",
    },

    # ── Team: Customer Wellness (3 agents) ────────────────────────────────
    {
        "id": "AGT-016", "name": "Anjali Menon",
        "team": "wellness", "team_name": "Customer Wellness",
        "skills": ["distress", "bereavement", "senior_citizen"],
        "languages": ["ml", "en", "hi"],
        "available": True,  "load": 0, "max_load": 3,
        "seniority": "senior",
    },
    {
        "id": "AGT-017", "name": "Suresh Kumar",
        "team": "wellness", "team_name": "Customer Wellness",
        "skills": ["distress", "bereavement"],
        "languages": ["kn", "hi", "en"],
        "available": True,  "load": 1, "max_load": 3,
        "seniority": "mid",
    },
    {
        "id": "AGT-018", "name": "Pooja Agarwal",
        "team": "wellness", "team_name": "Customer Wellness",
        "skills": ["distress", "senior_citizen", "requested_human"],
        "languages": ["hi", "en"],
        "available": True,  "load": 0, "max_load": 3,
        "seniority": "junior",
    },

    # ── Team: Senior / Escalation (2 agents) ──────────────────────────────
    {
        "id": "AGT-019", "name": "Rajesh Nambiar",
        "team": "senior", "team_name": "Senior / Escalation",
        "skills": ["distress","mis_selling","complaint","legal","high_value","bereavement"],
        "languages": ["en", "hi", "ml", "ta"],
        "available": True,  "load": 0, "max_load": 2,
        "seniority": "manager",
    },
    {
        "id": "AGT-020", "name": "Kavitha Reddy",
        "team": "senior", "team_name": "Senior / Escalation",
        "skills": ["distress","mis_selling","complaint","legal","nri","high_value"],
        "languages": ["te", "kn", "en", "hi"],
        "available": True,  "load": 0, "max_load": 2,
        "seniority": "manager",
    },
]

# ── Escalation reason → required skill mapping ─────────────────────────────────

REASON_SKILL_MAP: dict[str, str] = {
    "distress":        "distress",
    "mis_selling":     "mis_selling",
    "bereavement":     "bereavement",
    "complaint":       "complaint",
    "requested_human": "requested_human",
    "payment_failure": "payment_query",
    "medical_query":   "medical_query",
    "legal":           "legal",
    "legal_threat":    "legal",
}


# ── Queue item model ──────────────────────────────────────────────────────────

@dataclass
class QueueItem:
    case:          EscalationCase
    assigned_to:   Optional[str] = None
    agent_name:    Optional[str] = None
    sla_deadline:  Optional[datetime] = None
    sla_breached:  bool = False
    brief:         str = ""
    created_at:    datetime = field(default_factory=datetime.now)


@dataclass
class QueueStats:
    total_open:    int = 0
    p1_count:      int = 0
    p2_count:      int = 0
    p3_count:      int = 0
    p4_count:      int = 0
    sla_breached:  int = 0
    assigned:      int = 0
    unassigned:    int = 0
    available_agents: int = 0


# ── DB helpers ────────────────────────────────────────────────────────────────

def _ensure_queue_table(conn: sqlite3.Connection) -> None:
    """Create table if it doesn't exist. If it exists (older schema), add missing columns."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS escalation_cases (
            case_id         TEXT PRIMARY KEY,
            journey_id      TEXT,
            policy_number   TEXT,
            customer_id     TEXT,
            reason          TEXT,
            priority        TEXT,
            briefing_note   TEXT,
            assigned_to     TEXT,
            agent_name      TEXT,
            resolved        INTEGER DEFAULT 0,
            resolution_note TEXT,
            created_at      TEXT,
            resolved_at     TEXT,
            sla_deadline    TEXT,
            FOREIGN KEY (journey_id) REFERENCES renewal_journeys(journey_id)
        )
    """)
    # Ensure agent_name column exists (older DB may lack it)
    try:
        conn.execute("ALTER TABLE escalation_cases ADD COLUMN agent_name TEXT")
    except Exception:
        pass  # Column already exists
    conn.commit()


def _load_open_cases(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("""
        SELECT * FROM escalation_cases
        WHERE resolved = 0
        ORDER BY
            CASE priority
                WHEN 'p1_urgent' THEN 0
                WHEN 'p2_high'   THEN 1
                WHEN 'p3_normal' THEN 2
                WHEN 'p4_low'    THEN 3
                ELSE 4
            END,
            created_at ASC
    """).fetchall()
    return [dict(r) for r in rows]


# ── Mock brief generator ──────────────────────────────────────────────────────

_BRIEF_TEMPLATES = {
    EscalationReason.DISTRESS.value: (
        "⚠️ Customer {name} (Policy: {policy}) has shown signs of financial or emotional distress. "
        "Approach with empathy. Do NOT discuss premium immediately. "
        "Offer payment deferral or EMI options. Listen first."
    ),
    EscalationReason.MIS_SELLING.value: (
        "🚨 Customer {name} claims mis-selling on Policy {policy}. "
        "Pull original proposal document and KYC before calling. "
        "Do not agree or disagree with claim. Escalate to compliance if needed."
    ),
    EscalationReason.BEREAVEMENT.value: (
        "🙏 Customer {name} has experienced a bereavement. "
        "Express condolences first. Do not discuss renewal on first call. "
        "Offer a 30-day grace period extension. Involve senior agent if needed."
    ),
    EscalationReason.REQUESTED_HUMAN.value: (
        "👤 Customer {name} (Policy: {policy}) specifically requested a human agent. "
        "High touch required. Confirm policy details and address any concerns directly."
    ),
    EscalationReason.COMPLAINT.value: (
        "📋 Formal complaint from {name} regarding Policy {policy}. "
        "Log in CRM immediately. IRDAI response deadline: 14 days. "
        "Provide written acknowledgement within 3 days."
    ),
}

_DEFAULT_BRIEF = (
    "Customer {name} (Policy: {policy}) requires human follow-up. "
    "Review policy details and recent interaction history before calling."
)


def _mock_brief(case: EscalationCase, customer_name: str = "the customer") -> str:
    template = _BRIEF_TEMPLATES.get(case.reason.value, _DEFAULT_BRIEF)
    return template.format(name=customer_name, policy=case.policy_number)


# ── Import prompt ─────────────────────────────────────────────────────────────

from prompts.layer5 import BRIEF_PROMPT


# ── Agent assignment ──────────────────────────────────────────────────────────

def _assign_agent(
    priority:   str,
    reason:     str = "",
    language:   str = "en",
) -> tuple[Optional[str], Optional[str]]:
    """
    Skill-based agent assignment.

    Priority:
      1. Available agents with matching skill + matching language
      2. Available agents with matching skill (any language)
      3. P1_URGENT: any available agent below max_load (fallback)
      4. Any available agent below max_load (no match)
    """
    required_skill = REASON_SKILL_MAP.get(reason, "requested_human")

    def _eligible(a: dict) -> bool:
        return a["available"] and a["load"] < a.get("max_load", 5)

    candidates = [a for a in MOCK_AGENTS if _eligible(a)]
    if not candidates:
        return None, None

    # Tier 1: skill match + language match
    tier1 = [
        a for a in candidates
        if required_skill in a.get("skills", [])
        and language in a.get("languages", [])
    ]
    # Tier 2: skill match only
    tier2 = [
        a for a in candidates
        if required_skill in a.get("skills", [])
    ]
    # Tier 3: any available (P1 urgent fallback)
    tier3 = candidates

    # P1 urgent always escalates to senior/manager if available
    if priority == EscalationPriority.P1_URGENT.value:
        senior_pool = [
            a for a in (tier1 or tier2 or tier3)
            if a.get("seniority") in ("senior", "manager")
        ]
        pool = senior_pool or tier1 or tier2 or tier3
    else:
        pool = tier1 or tier2 or tier3

    pool.sort(key=lambda a: a["load"])
    agent = pool[0]
    agent["load"] += 1
    return agent["id"], agent["name"]



# ── Main manager ──────────────────────────────────────────────────────────────

class QueueManager:
    """Human escalation queue — load, prioritise, assign, brief, resolve."""

    def __init__(self):
        self._db_path = str(settings.abs_db_path)
        if not settings.mock_delivery:
            self._client = genai.Client(api_key=settings.gemini_api_key)
        logger.info(f"QueueManager ready | mock={settings.mock_delivery}")

    def load_queue(self) -> list[QueueItem]:
        """Load all open escalation cases, assign agents, generate briefs."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        _ensure_queue_table(conn)

        raw_cases = _load_open_cases(conn)
        conn.close()

        if not raw_cases:
            logger.info("Escalation queue is empty")
            return []

        # Get customer names
        conn2 = sqlite3.connect(self._db_path)
        conn2.row_factory = sqlite3.Row

        queue: list[QueueItem] = []
        for raw in raw_cases:
            # Build EscalationCase
            case = EscalationCase(
                case_id       = raw["case_id"],
                journey_id    = raw["journey_id"],
                policy_number = raw["policy_number"],
                customer_id   = raw["customer_id"],
                reason        = EscalationReason(raw["reason"]),
                priority      = EscalationPriority(raw["priority"]),
                briefing_note = raw["briefing_note"] or "",
            )

            # SLA deadline
            created_at_str = raw.get("created_at") or datetime.now().isoformat()
            try:
                created_at = datetime.fromisoformat(created_at_str)
            except ValueError:
                created_at = datetime.now()
            sla_h    = SLA_HOURS.get(case.priority.value, 24)
            deadline = created_at + timedelta(hours=sla_h)
            breached = datetime.now() > deadline

            # Agent assignment
            agent_id, agent_name = (
                (raw.get("assigned_to"), raw.get("agent_name"))
                if raw.get("assigned_to")
                else _assign_agent(
                    priority = case.priority.value,
                    reason   = case.reason.value,
                    language = raw.get("language", "en"),
                )
            )

            # Brief
            cust_row = conn2.execute(
                "SELECT name FROM customers WHERE customer_id=?", (case.customer_id,)
            ).fetchone()
            cust_name = cust_row["name"] if cust_row else case.customer_id

            brief = _mock_brief(case, cust_name) if settings.mock_delivery else self._generate_brief(case)

            item = QueueItem(
                case         = case,
                assigned_to  = agent_id,
                agent_name   = agent_name,
                sla_deadline = deadline,
                sla_breached = breached,
                brief        = brief,
            )
            queue.append(item)

            # Persist assignment if new
            if agent_id and not raw.get("assigned_to"):
                conn2.execute("""
                    UPDATE escalation_cases
                    SET assigned_to=?, agent_name=?
                    WHERE case_id=?
                """, (agent_id, agent_name, case.case_id))

        conn2.commit()
        conn2.close()

        logger.info(
            f"Queue loaded: {len(queue)} cases | "
            f"P1:{sum(1 for q in queue if q.case.priority == EscalationPriority.P1_URGENT)} "
            f"P2:{sum(1 for q in queue if q.case.priority == EscalationPriority.P2_HIGH)} "
            f"P3:{sum(1 for q in queue if q.case.priority == EscalationPriority.P3_NORMAL)} "
            f"P4:{sum(1 for q in queue if q.case.priority == EscalationPriority.P4_LOW)}"
        )
        return queue

    def resolve(
        self,
        case_id:         str,
        resolution_note: str,
        resolved_by:     str = "human_agent",
    ) -> bool:
        """Mark a case as resolved. Updates journey status."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("""
            UPDATE escalation_cases
            SET resolved=1, resolution_note=?, resolved_at=?
            WHERE case_id=?
        """, (resolution_note, datetime.now().isoformat(), case_id))
        # Get journey_id and re-open
        row = conn.execute(
            "SELECT journey_id FROM escalation_cases WHERE case_id=?", (case_id,)
        ).fetchone()
        if row:
            conn.execute("""
                UPDATE renewal_journeys SET status='in_progress' WHERE journey_id=?
            """, (row[0],))
        conn.commit()
        conn.close()
        logger.info(f"Case {case_id} resolved by {resolved_by}")
        return True

    def get_stats(self, queue: list[QueueItem]) -> QueueStats:
        return QueueStats(
            total_open       = len(queue),
            p1_count         = sum(1 for q in queue if q.case.priority == EscalationPriority.P1_URGENT),
            p2_count         = sum(1 for q in queue if q.case.priority == EscalationPriority.P2_HIGH),
            p3_count         = sum(1 for q in queue if q.case.priority == EscalationPriority.P3_NORMAL),
            p4_count         = sum(1 for q in queue if q.case.priority == EscalationPriority.P4_LOW),
            sla_breached     = sum(1 for q in queue if q.sla_breached),
            assigned         = sum(1 for q in queue if q.assigned_to),
            unassigned       = sum(1 for q in queue if not q.assigned_to),
            available_agents = sum(
                1 for a in MOCK_AGENTS
                if a["available"] and a["load"] < a.get("max_load", 5)
            ),
        )

    def get_specialist_roster(self) -> list[dict]:
        """Return full 20-specialist roster with current status."""
        return [
            {
                "id":         a["id"],
                "name":       a["name"],
                "team":       a["team_name"],
                "skills":     ", ".join(a.get("skills", [])),
                "languages":  ", ".join(a.get("languages", [])),
                "seniority":  a.get("seniority", ""),
                "available":  a["available"],
                "load":       a["load"],
                "max_load":   a.get("max_load", 5),
                "capacity":   f"{a['load']}/{a.get('max_load',5)}",
            }
            for a in MOCK_AGENTS
        ]

    # ── Test-accessible helpers ───────────────────────────────────────────────

    def _db_add_case(self, conn: sqlite3.Connection, case: "EscalationCase") -> None:
        """Insert an escalation case into the DB. Used by tests."""
        conn.execute("""
            INSERT OR IGNORE INTO escalation_cases
                (case_id, journey_id, policy_number, customer_id, reason, priority,
                 briefing_note, resolved, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
        """, (
            case.case_id, case.journey_id, case.policy_number, case.customer_id,
            case.reason.value, case.priority.value, case.briefing_note,
            datetime.now().isoformat(),
        ))

    def _select_agent(self, reason: str, language: str = "en",
                      priority: str = "p3_normal") -> Optional[dict]:
        """Select best available agent for the given reason/language/priority.
        Returns the raw agent dict from self.agents (defaults to MOCK_AGENTS)."""
        agents = getattr(self, "agents", MOCK_AGENTS)
        required_skill = REASON_SKILL_MAP.get(reason, "requested_human")

        def _eligible(a: dict) -> bool:
            return a["available"] and a["load"] < a.get("max_load", 5)

        candidates = [a for a in agents if _eligible(a)]
        if not candidates:
            return None

        tier1 = [
            a for a in candidates
            if required_skill in a.get("skills", [])
            and language in a.get("languages", [])
        ]
        tier2 = [a for a in candidates if required_skill in a.get("skills", [])]

        if priority == EscalationPriority.P1_URGENT.value:
            senior_pool = [
                a for a in (tier1 or tier2 or candidates)
                if a.get("seniority") in ("senior", "manager")
            ]
            pool = senior_pool or tier1 or tier2 or candidates
        else:
            pool = tier1 or tier2 or candidates

        pool.sort(key=lambda a: a["load"])
        return pool[0]

    def _db_resolve_case(self, conn: sqlite3.Connection, case_id: str,
                         resolution_note: str) -> None:
        """Mark a case as resolved in the DB. Used by tests."""
        conn.execute("""
            UPDATE escalation_cases
            SET resolved=1, resolution_note=?, resolved_at=?
            WHERE case_id=?
        """, (resolution_note, datetime.now().isoformat(), case_id))

    def _generate_brief(self, case: EscalationCase) -> str:
        prompt = BRIEF_PROMPT.format(
            case_id       = case.case_id,
            reason        = case.reason.value,
            priority      = case.priority.value,
            policy_number = case.policy_number,
            briefing_note = case.briefing_note,
        )
        try:
            response = self._client.models.generate_content(
                model    = settings.model_classify,
                contents = prompt,
            )
            return response.text.strip()
        except Exception as e:
            logger.warning(f"Brief generation failed: {e}")
            return case.briefing_note
