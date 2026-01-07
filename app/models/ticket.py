"""Ticket model - tracking webhook events and their status."""

import secrets
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Optional

from beanie import Document, Indexed
from pydantic import BaseModel, Field


class TicketStatus(str, Enum):
    IGNORED = "ignored"  # HACK: this is for aliyun where normal messages should not create ticket
    PENDING = "pending"  # Awaiting acknowledgement
    ACKNOWLEDGED = "acknowledged"  # Someone has acknowledged
    ESCALATED = "escalated"  # Escalated to next notification group
    RESOLVED = "resolved"  # Issue resolved (e.g., alert cleared)


class EventType(str, Enum):
    CREATED = "created"
    NOTIFIED = "notified"
    NOTIFIED_SILENCED = "notified_silenced"
    REPEATED = "repeated"
    ESCALATED = "escalated"
    MAX_LEVEL_REACHED = "max_level_reached"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class TicketEvent(BaseModel):
    """A single event in the ticket timeline."""

    type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    level: Optional[int] = None  # Notification group level
    group_name: Optional[str] = None  # Notification group name
    success: Optional[bool] = None  # For notification events
    details: str = ""


class Ticket(Document):
    """Ticket representing a webhook event.

    Each webhook call creates a ticket that tracks:
    - The original payload
    - Current status
    - Acknowledgement details
    - Escalation history
    - Timeline of events
    """

    project_id: Annotated[str, Indexed(str)]  # Reference to Project._id as string
    source: str  # e.g., "grafana", "alertmanager", "custom"
    status: TicketStatus = TicketStatus.PENDING
    escalation_level: int = 1  # Current notification group priority level

    # Payload from the webhook
    payload: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)

    # Parsed data from source parser (e.g., Grafana alerts)
    parsed_data: Optional[dict[str, Any]] = None

    # Basic ticket info (extracted from payload or parsed_data)
    title: str = ""
    description: str = ""
    severity: str = ""

    # Acknowledgement tracking
    ack_token: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None  # User._id as string or "link"

    # Notification tracking
    last_notified_at: Optional[datetime] = None
    notification_count: int = 0

    # Event timeline
    events: list[TicketEvent] = Field(default_factory=list)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None

    class Settings:
        name = "tickets"
        use_state_management = True
        indexes = [
            "status",
            "created_at",
            [("project_id", 1), ("status", 1)],
            [("project_id", 1), ("created_at", -1)],
        ]

    def is_pending(self) -> bool:
        return self.status == TicketStatus.PENDING

    def is_acknowledged(self) -> bool:
        return self.status == TicketStatus.ACKNOWLEDGED

    def is_resolved(self) -> bool:
        return self.status == TicketStatus.RESOLVED

    def is_ignored(self) -> bool:
        return self.status == TicketStatus.IGNORED

    def can_escalate(self) -> bool:
        """Check if ticket can be escalated.

        Escalation is only allowed for:
        - Tickets with pending or escalated status
        - Tickets with severity = 'critical'
        """
        if self.status not in (TicketStatus.PENDING, TicketStatus.ESCALATED):
            return False
        return self.severity.lower() == "critical" if self.severity else False

    def add_event(
        self,
        event_type: EventType,
        level: Optional[int] = None,
        group_name: Optional[str] = None,
        success: Optional[bool] = None,
        details: str = "",
    ) -> None:
        """Add an event to the timeline."""
        event = TicketEvent(
            type=event_type,
            timestamp=datetime.utcnow(),
            level=level,
            group_name=group_name,
            success=success,
            details=details,
        )
        self.events.append(event)
