"""Unified alert model for all sources."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# AlertStatus = Literal["firing", "resolved"]
# HACK: this is for aliyun where normal messages should be ignored
AlertStatus = Literal["ignored", "firing", "resolved"]


class Alert(BaseModel):
    """Unified alert representation from any source."""

    source: str
    status: AlertStatus
    name: str = ""
    severity: str = "warning"
    summary: str = ""
    description: str = ""
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime
    ends_at: datetime | None = None
    generator_url: str = ""
    fingerprint: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_firing(self) -> bool:
        return self.status == "firing"

    # need this because status is no longer binary
    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"


class AlertGroup(BaseModel):
    """Group of alerts from a single webhook payload."""

    source: str
    status: AlertStatus
    alerts: list[Alert] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    external_url: str = ""
    receiver: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def firing_alerts(self) -> list[Alert]:
        return [a for a in self.alerts if a.is_firing]

    @property
    def resolved_alerts(self) -> list[Alert]:
        return [a for a in self.alerts if a.is_resolved]

    @property
    def is_firing(self) -> bool:
        return self.status == "firing"
