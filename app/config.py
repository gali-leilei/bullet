"""Configuration management for Bullet."""

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server settings
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=5032)
    log_level: str = Field(default="INFO")
    base_url: str = Field(default="http://localhost:5032")

    # MongoDB
    mongodb_uri: str = Field(default="mongodb://localhost:27017")
    mongodb_database: str = Field(default="bullet")

    # Session & Auth
    secret_key: str = Field(default_factory=lambda: secrets.token_hex(32))
    session_cookie_name: str = Field(default="bullet_session")
    session_max_age: int = Field(default=86400 * 7)  # 7 days

    # Initial admin (created on first startup if no users exist)
    admin_username: str = Field(default="admin")
    admin_password: str = Field(default="")  # Must be set via env
    admin_email: str = Field(default="admin@localhost")

    # Routes configuration (legacy, for backward compatibility)
    routes_config: str = Field(default="routes.yaml")

    # Resend email channel
    resend_api_key: str = Field(default="")
    resend_from_email: str = Field(default="")
    resend_api_url: str = Field(default="https://api.resend.com/emails")

    # Twilio SMS channel
    twilio_account_sid: str = Field(default="")
    twilio_auth_token: str = Field(default="")
    twilio_from_number: str = Field(default="")

    # Escalation settings
    escalation_check_interval: int = Field(default=5)  # seconds

    @property
    def routes_config_path(self) -> Path:
        return Path(self.routes_config)


@lru_cache
def get_settings() -> Settings:
    return Settings()

