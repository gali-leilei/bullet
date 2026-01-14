"""Project model - notification target configuration."""

from datetime import datetime
from typing import Annotated, Optional

from beanie import Document, Indexed
from pydantic import BaseModel, Field


class EscalationConfig(BaseModel):
    """Configuration for ticket escalation."""

    enabled: bool = False
    timeout_minutes: int = 15  # Escalate if not acknowledged within N minutes


class Project(Document):
    """Project within a namespace.

    Each project binds to notification groups that define the escalation path.
    The order of notification_group_ids determines the escalation sequence.

    Webhook URL: /webhook/{namespace_slug}/{project_id}?source=grafana
    """

    namespace_id: Annotated[str, Indexed(str)]  # Reference to Namespace._id as string
    name: str
    description: str = ""
    notification_group_ids: list[str] = Field(
        default_factory=list
    )  # Ordered list of NotificationGroup._id
    notification_template_id: Optional[str] = (
        None  # NotificationTemplate._id, None uses default
    )
    escalation_config: EscalationConfig = Field(default_factory=EscalationConfig)
    is_active: bool = True
    notify_on_ack: bool = False  # Send notification when ticket is acknowledged
    silenced_until: Optional[datetime] = (
        None  # If set and in future, notifications are silenced
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "projects"
        use_state_management = True

    def is_silenced(self) -> bool:
        """Check if the project is currently silenced."""
        if self.silenced_until is None:
            return False
        return datetime.utcnow() < self.silenced_until

    def silence_remaining(self) -> Optional[str]:
        """Get human-readable remaining silence time."""
        if not self.is_silenced():
            return None
        assert self.silenced_until is not None, "silenced_until is None"
        remaining = self.silenced_until - datetime.utcnow()
        total_seconds = int(remaining.total_seconds())
        if total_seconds < 60:
            return f"{total_seconds}秒"
        elif total_seconds < 3600:
            return f"{total_seconds // 60}分钟"
        else:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            if minutes > 0:
                return f"{hours}小时{minutes}分钟"
            return f"{hours}小时"


# Available silence duration options (minutes)
SILENCE_DURATION_OPTIONS = [
    (5, "5 分钟"),
    (10, "10 分钟"),
    (15, "15 分钟"),
    (30, "30 分钟"),
    (60, "1 小时"),
    (120, "2 小时"),
    (360, "6 小时"),
    (720, "12 小时"),
    (1440, "24 小时"),
]
