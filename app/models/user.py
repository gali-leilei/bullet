"""User model for authentication and authorization."""

from datetime import datetime
from enum import Enum
from typing import Optional

from beanie import Document, Indexed
from pydantic import EmailStr, Field


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"


class User(Document):
    """System user for authentication."""

    username: Indexed(str, unique=True)
    password_hash: str
    email: Optional[EmailStr] = None
    role: UserRole = UserRole.USER
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_login_at: Optional[datetime] = None

    class Settings:
        name = "users"
        use_state_management = True

    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

