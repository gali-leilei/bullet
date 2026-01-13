"""NotificationGroup model - global notification routing configuration."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Optional

from beanie import Document, Indexed
from pydantic import BaseModel, Field


class ChannelType(str, Enum):
    FEISHU = "feishu"
    EMAIL = "email"
    SMS = "sms"
    SLACK = "slack"


class RepeatInterval(int, Enum):
    """Repeat notification interval in minutes. None means no repeat."""

    NONE = 0
    ONE_MINUTE = 1
    FIVE_MINUTES = 5
    TEN_MINUTES = 10
    THIRTY_MINUTES = 30


class ChannelConfig(BaseModel):
    """Channel configuration within a notification group.

    The channel will send to contacts based on the channel type:
    - feishu: uses contact.feishu_webhook_url
    - email: uses contact.emails
    - sms: uses contact.phones
    """

    type: ChannelType
    contact_ids: list[str] = Field(default_factory=list)  # Contact._id as strings


class NotificationGroup(Document):
    """Global notification group.

    Notification groups are shared resources that can be bound to multiple projects.
    Projects define their escalation path by ordering notification groups.
    """

    name: Annotated[str, Indexed(str, unique=True)]
    description: str = ""
    repeat_interval: Optional[int] = (
        None  # Minutes between repeat notifications, None = no repeat
    )
    channel_configs: list[ChannelConfig] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "notification_groups"
        use_state_management = True

    class Config:
        json_schema_extra = {
            "example": {
                "name": "On-call Team",
                "description": "Primary on-call team for alerts",
                "repeat_interval": 5,
                "channel_configs": [
                    {
                        "type": "feishu",
                        "contact_ids": ["507f1f77bcf86cd799439012"],
                    }
                ],
            }
        }


# Available repeat intervals for UI
REPEAT_INTERVAL_OPTIONS = [
    (None, "不重复"),
    (1, "1 分钟"),
    (5, "5 分钟"),
    (10, "10 分钟"),
    (30, "30 分钟"),
]
