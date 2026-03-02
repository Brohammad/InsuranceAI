"""
core/models.py
──────────────
All Pydantic data models for Project RenewAI.
These are the canonical data structures shared across every agent.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════════════
#  ENUMS
# ═══════════════════════════════════════════════════════════════════════════════

class ProductType(str, Enum):
    TERM        = "term"
    ENDOWMENT   = "endowment"
    ULIP        = "ulip"
    PENSION     = "pension"
    MONEY_BACK  = "money_back"
    HEALTH      = "health"


class PolicyStatus(str, Enum):
    ACTIVE      = "active"
    LAPSED      = "lapsed"
    SURRENDERED = "surrendered"
    PAID_UP     = "paid_up"
    MATURED     = "matured"


class CustomerSegment(str, Enum):
    AUTO_RENEWER    = "auto_renewer"
    WEALTH_BUILDER  = "wealth_builder"
    NUDGE_NEEDED    = "nudge_needed"
    PRICE_SENSITIVE = "price_sensitive"
    HIGH_RISK       = "high_risk"
    DISTRESS        = "distress"


class Channel(str, Enum):
    EMAIL     = "email"
    WHATSAPP  = "whatsapp"
    VOICE     = "voice"
    SMS       = "sms"
    HUMAN     = "human"


class Language(str, Enum):
    ENGLISH   = "english"
    HINDI     = "hindi"
    MARATHI   = "marathi"
    BENGALI   = "bengali"
    TAMIL     = "tamil"
    TELUGU    = "telugu"
    KANNADA   = "kannada"
    MALAYALAM = "malayalam"
    GUJARATI  = "gujarati"


class JourneyStatus(str, Enum):
    NOT_STARTED  = "not_started"
    IN_PROGRESS  = "in_progress"
    PAYMENT_DONE = "payment_done"
    ESCALATED    = "escalated"
    LAPSED       = "lapsed"
    OPTED_OUT    = "opted_out"


class InteractionOutcome(str, Enum):
    SENT           = "sent"
    DELIVERED      = "delivered"
    READ           = "read"
    RESPONDED      = "responded"
    PAYMENT_MADE   = "payment_made"
    OBJECTION      = "objection"
    ESCALATED      = "escalated"
    NO_RESPONSE    = "no_response"
    BOUNCED        = "bounced"
    OPT_OUT        = "opt_out"


class EscalationPriority(str, Enum):
    P1_URGENT = "p1_urgent"    # 2h SLA — distress, bereavement, legal
    P2_HIGH   = "p2_high"      # 4h SLA — HNI, high-value policy
    P3_NORMAL = "p3_normal"    # 24h SLA — complex queries
    P4_LOW    = "p4_low"       # 48h SLA — general human preference


class EscalationReason(str, Enum):
    BEREAVEMENT          = "bereavement"
    FINANCIAL_HARDSHIP   = "financial_hardship"
    DISTRESS             = "distress"
    MIS_SELLING          = "mis_selling"
    LEGAL_THREAT         = "legal_threat"
    OMBUDSMAN            = "ombudsman"
    REQUESTED_HUMAN      = "requested_human"
    UNRESOLVED_OBJECTION = "unresolved_objection"
    HNI_POLICY           = "hni_policy"
    MEDICAL_REUNDERWRITE = "medical_reunderwrite"
    COMPLAINT            = "complaint"


# ═══════════════════════════════════════════════════════════════════════════════
#  CUSTOMER
# ═══════════════════════════════════════════════════════════════════════════════

class Customer(BaseModel):
    customer_id:         str
    name:                str
    age:                 int
    gender:              str                  # M / F / Other
    city:                str
    state:               str
    preferred_language:  Language
    preferred_channel:   Channel
    preferred_call_time: str                  # e.g. "18:00-20:00"
    email:               str
    phone:               str
    whatsapp_number:     str
    occupation:          str                  # e.g. "IT Professional"
    is_on_dnd:           bool = False
    created_at:          datetime = Field(default_factory=datetime.now)


# ═══════════════════════════════════════════════════════════════════════════════
#  POLICY
# ═══════════════════════════════════════════════════════════════════════════════

class Policy(BaseModel):
    policy_number:       str
    customer_id:         str
    product_type:        ProductType
    product_name:        str                  # e.g. "Term Shield"
    sum_assured:         float                # in INR
    annual_premium:      float                # in INR
    policy_start_date:   date
    renewal_due_date:    date
    tenure_years:        int
    years_completed:     int
    status:              PolicyStatus = PolicyStatus.ACTIVE
    payment_mode:        str = "annual"       # annual / semi-annual / monthly
    has_auto_debit:      bool = False
    payment_history:     list[str] = Field(default_factory=list)  # "on_time" / "late" / "missed"
    last_payment_date:   Optional[date] = None
    grace_period_days:   int = 30


# ═══════════════════════════════════════════════════════════════════════════════
#  RENEWAL JOURNEY
# ═══════════════════════════════════════════════════════════════════════════════

class JourneyStep(BaseModel):
    """One planned step in the renewal journey."""
    step_number:     int
    trigger_days:    int                  # days before renewal due date (negative = before, positive = after)
    channel:         Channel
    strategy:        str                  # e.g. "tax_benefit_reminder"
    tone:            str                  # e.g. "friendly"
    scheduled_time:  Optional[str] = None # e.g. "18:30"
    completed:       bool = False
    completed_at:    Optional[datetime] = None
    outcome:         Optional[InteractionOutcome] = None


class RenewalJourney(BaseModel):
    journey_id:          str
    policy_number:       str
    customer_id:         str
    status:              JourneyStatus = JourneyStatus.NOT_STARTED
    segment:             Optional[CustomerSegment] = None
    lapse_score:         Optional[int] = None          # 0-100
    channel_sequence:    list[Channel] = Field(default_factory=list)
    steps:               list[JourneyStep] = Field(default_factory=list)
    current_step_index:  int = 0
    payment_received:    bool = False
    payment_received_at: Optional[datetime] = None
    escalated:           bool = False
    escalation_reason:   Optional[EscalationReason] = None
    created_at:          datetime = Field(default_factory=datetime.now)
    updated_at:          datetime = Field(default_factory=datetime.now)


# ═══════════════════════════════════════════════════════════════════════════════
#  INTERACTION LOG
# ═══════════════════════════════════════════════════════════════════════════════

class Interaction(BaseModel):
    interaction_id:   str
    journey_id:       str
    policy_number:    str
    customer_id:      str
    channel:          Channel
    direction:        str                      # "outbound" / "inbound"
    message_content:  str
    language:         Language
    sent_at:          Optional[datetime] = None
    outcome:          Optional[InteractionOutcome] = None
    sentiment_score:  Optional[float] = None   # -10 to +10
    quality_score:    Optional[float] = None   # 0-100
    critique_passed:  Optional[bool] = None
    safety_flags:     list[str] = Field(default_factory=list)
    raw_response:     Optional[str] = None     # customer's reply if any


# ═══════════════════════════════════════════════════════════════════════════════
#  ESCALATION
# ═══════════════════════════════════════════════════════════════════════════════

class EscalationCase(BaseModel):
    case_id:          str
    journey_id:       str
    policy_number:    str
    customer_id:      str
    reason:           EscalationReason
    priority:         EscalationPriority
    briefing_note:    str                      # AI-generated context for human
    assigned_to:      Optional[str] = None     # human specialist name
    resolved:         bool = False
    resolved_at:      Optional[datetime] = None
    resolution_note:  Optional[str] = None
    created_at:       datetime = Field(default_factory=datetime.now)
    sla_deadline:     Optional[datetime] = None


# ═══════════════════════════════════════════════════════════════════════════════
#  SEGMENTATION RESULT
# ═══════════════════════════════════════════════════════════════════════════════

class SegmentationResult(BaseModel):
    customer_id:        str
    policy_number:      str
    segment:            CustomerSegment
    recommended_tone:   str
    recommended_strategy: str
    risk_flag:          str                    # "low" / "medium" / "high"
    reasoning:          str


# ═══════════════════════════════════════════════════════════════════════════════
#  CRITIQUE RESULT
# ═══════════════════════════════════════════════════════════════════════════════

class CritiqueResult(BaseModel):
    approved:               bool
    # Legacy fields
    issues:                 list[str] = Field(default_factory=list)
    suggestions:            list[str] = Field(default_factory=list)
    revised_content:        Optional[str] = None
    # Extended quality fields (Layer 3)
    tone_score:             int = 7
    accuracy_score:         int = 7
    personalisation_score:  int = 7
    conversion_likelihood:  int = 7
    rewrite:                Optional[str] = None
    overall_verdict:        str = ""


# ═══════════════════════════════════════════════════════════════════════════════
#  SAFETY CHECK RESULT
# ═══════════════════════════════════════════════════════════════════════════════

class SafetyCheckResult(BaseModel):
    is_safe:           bool
    distress_detected: bool = False
    flags:             list[str] = Field(default_factory=list)
    severity:          str = "low"             # "low" / "medium" / "high" / "critical"
    action_required:   str = "none"            # "none" / "flag" / "pause" / "escalate_immediately"
