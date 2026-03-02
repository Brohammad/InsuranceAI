"""
integrations/crm_stub.py
─────────────────────────
CRM Integration Stub — Suraksha Life Insurance

In production this would call the internal CRM REST API (e.g. Salesforce / Zoho / custom).
In mock mode all operations are no-ops that return realistic stub responses.

Covers:
  • upsert_contact()       — create or update customer record
  • log_interaction()      — push a communication event to CRM timeline
  • get_contact()          — pull customer profile from CRM
  • update_journey_status()— update renewal journey stage in CRM pipeline
  • create_follow_up_task()— create a follow-up task for a human agent
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from loguru import logger

from core.config import settings


# ── Response models ────────────────────────────────────────────────────────────

@dataclass
class CrmContact:
    crm_id:      str
    customer_id: str
    name:        str
    phone:       str
    email:       str
    city:        str
    language:    str
    synced_at:   str
    mock:        bool = True


@dataclass
class CrmInteractionLog:
    log_id:      str
    crm_id:      str
    channel:     str
    direction:   str
    summary:     str
    outcome:     str
    logged_at:   str
    mock:        bool = True


@dataclass
class CrmTask:
    task_id:    str
    crm_id:     str
    title:      str
    due_date:   str
    assigned_to:str
    priority:   str
    created_at: str
    mock:       bool = True


# ── CRM stub ──────────────────────────────────────────────────────────────────

class CrmStub:
    """
    Stub CRM client. In real mode: calls CRM REST API.
    In mock mode: returns plausible stub data and logs only.
    """

    def __init__(self):
        self.mock = settings.mock_delivery
        logger.info(f"CrmStub ready | mock={self.mock}")

    def upsert_contact(
        self,
        customer_id: str,
        name:        str,
        phone:       str,
        email:       str,
        city:        str = "",
        language:    str = "en",
        extra:       Optional[dict[str, Any]] = None,
    ) -> CrmContact:
        """Create or update a CRM contact. Returns the CRM record."""
        if self.mock:
            contact = CrmContact(
                crm_id      = f"CRM-{customer_id}",
                customer_id = customer_id,
                name        = name,
                phone       = phone,
                email       = email,
                city        = city,
                language    = language,
                synced_at   = datetime.now().isoformat(),
                mock        = True,
            )
            logger.info(f"[CRM STUB] upsert_contact | {customer_id} → {contact.crm_id}")
            return contact

        # ── Real mode: call CRM API ───────────────────────────────────────────
        raise NotImplementedError(
            "Real CRM integration not configured. "
            "Set CRM_BASE_URL and CRM_API_KEY in .env"
        )

    def log_interaction(
        self,
        customer_id: str,
        channel:     str,
        direction:   str,
        summary:     str,
        outcome:     str = "delivered",
    ) -> CrmInteractionLog:
        """Push a communication event to the CRM contact timeline."""
        if self.mock:
            log = CrmInteractionLog(
                log_id    = str(uuid.uuid4()),
                crm_id    = f"CRM-{customer_id}",
                channel   = channel,
                direction = direction,
                summary   = summary[:200],
                outcome   = outcome,
                logged_at = datetime.now().isoformat(),
                mock      = True,
            )
            logger.info(f"[CRM STUB] log_interaction | {customer_id} | {channel} | {outcome}")
            return log

        raise NotImplementedError("Real CRM interaction log not implemented")

    def get_contact(self, customer_id: str) -> Optional[CrmContact]:
        """Pull customer profile from CRM. Returns None if not found."""
        if self.mock:
            logger.info(f"[CRM STUB] get_contact | {customer_id}")
            return CrmContact(
                crm_id      = f"CRM-{customer_id}",
                customer_id = customer_id,
                name        = "Mock Customer",
                phone       = "0000000000",
                email       = "mock@crm.test",
                city        = "Mumbai",
                language    = "en",
                synced_at   = datetime.now().isoformat(),
                mock        = True,
            )
        raise NotImplementedError("Real CRM get_contact not implemented")

    def update_journey_status(
        self,
        customer_id: str,
        policy_no:   str,
        stage:       str,
        notes:       str = "",
    ) -> bool:
        """Update the renewal pipeline stage in CRM."""
        if self.mock:
            logger.info(
                f"[CRM STUB] update_journey_status | {customer_id} / {policy_no} → {stage}"
            )
            return True
        raise NotImplementedError("Real CRM pipeline update not implemented")

    def create_follow_up_task(
        self,
        customer_id:  str,
        title:        str,
        due_in_hours: int   = 24,
        assigned_to:  str   = "team_renewal",
        priority:     str   = "normal",
    ) -> CrmTask:
        """Create a follow-up task on the CRM contact."""
        if self.mock:
            task = CrmTask(
                task_id    = str(uuid.uuid4()),
                crm_id     = f"CRM-{customer_id}",
                title      = title,
                due_date   = (datetime.now() + timedelta(hours=due_in_hours)).isoformat(),
                assigned_to= assigned_to,
                priority   = priority,
                created_at = datetime.now().isoformat(),
                mock       = True,
            )
            logger.info(f"[CRM STUB] create_follow_up_task | {customer_id} | '{title}'")
            return task
        raise NotImplementedError("Real CRM task creation not implemented")
