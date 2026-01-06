"""Twilio SMS notification channel."""

import logging
from typing import List

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

from app.channels.base import BaseChannel
from app.config import get_settings
from app.models.event import Event

logger = logging.getLogger(__name__)


class TwilioSMSChannel(BaseChannel):
    """Send notifications via Twilio SMS."""

    def __init__(
        self,
        account_sid: str = "",
        auth_token: str = "",
        from_number: str = "",
        to_numbers: List[str] | None = None,
        name: str = "twilio_sms",
        message_override: str | None = None,
    ):
        settings = get_settings()
        self._account_sid = account_sid or settings.twilio_account_sid
        self._auth_token = auth_token or settings.twilio_auth_token
        self._from_number = from_number or settings.twilio_from_number
        self._to_numbers = to_numbers or []
        self._name = name
        self._message_override = message_override
        self._client: Client | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def enabled(self) -> bool:
        return bool(self._account_sid and self._auth_token and self._from_number)

    def _get_client(self) -> Client:
        """Get or create Twilio client."""
        if self._client is None:
            self._client = Client(self._account_sid, self._auth_token)
        return self._client

    def _format_message(self, event: Event) -> str:
        """Format event into SMS message."""
        # Extract key info from payload
        payload = event.payload
        
        title = payload.get("title", "")
        if not title and "alerts" in payload and payload["alerts"]:
            # AlertGroup payload
            alert = payload["alerts"][0]
            title = alert.get("name", "") or alert.get("summary", "")
        
        source = event.source or "unknown"
        
        # Build short SMS message
        parts = [f"[{source}] {title}"]
        
        if event.labels:
            label_str = ", ".join(f"{k}={v}" for k, v in list(event.labels.items())[:3])
            parts.append(label_str)
        
        message = " | ".join(parts)
        
        # Truncate to SMS limit (160 chars for single SMS)
        if len(message) > 155:
            message = message[:152] + "..."
        
        return message

    async def send(self, event: Event) -> bool:
        """Send SMS notification."""
        if not self.enabled:
            logger.warning(f"Twilio SMS channel {self._name} is not configured")
            return False

        if not self._to_numbers:
            logger.warning(f"No recipient numbers configured for {self._name}")
            return False

        # Use template-rendered message if provided
        message_body = self._message_override if self._message_override else self._format_message(event)
        client = self._get_client()
        
        success_count = 0
        for to_number in self._to_numbers:
            try:
                message = client.messages.create(
                    body=message_body,
                    from_=self._from_number,
                    to=to_number,
                )
                logger.info(f"SMS sent to {to_number}: {message.sid}")
                success_count += 1
            except TwilioRestException as e:
                logger.error(f"Failed to send SMS to {to_number}: {e}")
            except Exception as e:
                logger.exception(f"Unexpected error sending SMS to {to_number}: {e}")

        return success_count > 0


async def send_sms(to_numbers: List[str], message: str) -> bool:
    """Convenience function to send SMS to multiple numbers."""
    settings = get_settings()
    
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        logger.warning("Twilio credentials not configured")
        return False

    channel = TwilioSMSChannel(to_numbers=to_numbers)
    
    # Create a simple event
    event = Event(
        source="system",
        type="notification",
        payload={"title": message},
    )
    
    return await channel.send(event)

