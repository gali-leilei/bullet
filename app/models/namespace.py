"""Namespace model - container for projects."""

from datetime import datetime
from typing import Annotated

from beanie import Document, Indexed
from pydantic import Field


class Namespace(Document):
    """Namespace for organizing projects.

    The slug is used in webhook URLs: /webhook/{slug}/{project_id}
    """

    name: str
    slug: Annotated[str, Indexed(str, unique=True)]
    description: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "namespaces"
        use_state_management = True
