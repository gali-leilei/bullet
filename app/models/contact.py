"""Contact model - address book for notifications."""

from datetime import datetime
from typing import Annotated

from beanie import Document, Indexed
from pydantic import Field


class Contact(Document):
    """Contact entry in the address book.

    A contact can represent a person (with phone/email) or a bot (with webhook URL).
    """

    name: Annotated[str, Indexed(str)]
    phones: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    feishu_webhook_url: str = ""
    note: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "contacts"
        use_state_management = True

    def has_feishu(self) -> bool:
        return bool(self.feishu_webhook_url)

    def has_email(self) -> bool:
        return len(self.emails) > 0

    def has_phone(self) -> bool:
        return len(self.phones) > 0
