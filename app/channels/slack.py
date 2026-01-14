"""Slack notification channel using Incoming Webhooks."""

import logging
from typing import Any

import httpx

from app.channels.base import BaseChannel
from app.models.event import Event

logger = logging.getLogger(__name__)

# Pre-rendered Slack blocks from template (passed via event.meta)
TEMPLATE_BLOCKS_KEY = "template_slack_blocks"


class SlackWebhookChannel(BaseChannel):
    """Slack notification channel using Incoming Webhooks."""

    def __init__(self, webhook_url: str):
        self._webhook_url = webhook_url

    @property
    def name(self) -> str:
        return "slack-webhook"

    @property
    def enabled(self) -> bool:
        return bool(self._webhook_url)

    def _get_severity_emoji(self, severity: str) -> str:
        """Get emoji based on severity level."""
        severity_map = {
            "critical": "🔴",
            "error": "🔴",
            "warning": "🟠",
            "info": "🔵",
        }
        return severity_map.get(severity.lower(), "🔵")

    def _build_text_message(self, event: Event) -> dict[str, Any]:
        """Build a simple text message for generic events."""
        import json

        payload_json = json.dumps(event.payload, ensure_ascii=False, indent=2, default=str)
        labels_json = json.dumps(event.labels or {}, ensure_ascii=False, default=str)
        text = (
            f"*[{(event.source or '').upper()}]* {event.type or 'event'}\n"
            f"*Labels:* {labels_json}\n"
            f"*Payload:*\n```{payload_json}```"
        )
        return {"text": text}

    def _build_ticket_blocks(self, event: Event) -> dict[str, Any]:
        """Build a rich Block Kit message for ticket notifications with ack link."""
        from app.config import get_settings

        settings = get_settings()

        meta = event.meta or {}
        ticket_id = meta.get("ticket_id", "")
        ack_token = meta.get("ack_token", "")
        title = meta.get("title", "") or event.payload.get("title", "Alert")
        description = meta.get("description", "") or ""
        severity = meta.get("severity", "") or "info"

        # Build URLs
        ack_url = f"{settings.base_url}/ack/{ticket_id}?token={ack_token}&format=html"
        detail_url = f"{settings.base_url}/tickets/{ticket_id}"

        severity_emoji = self._get_severity_emoji(severity)

        blocks: list[dict[str, Any]] = []

        # Header section
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{severity_emoji} {title}",
                "emoji": True,
            },
        })

        # Description section
        if description:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": description[:2000],  # Slack limit
                },
            })

        # Labels section
        if event.labels:
            label_text = " | ".join(f"`{k}={v}`" for k, v in list(event.labels.items())[:10])
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Labels:* {label_text}",
                },
            })

        # Divider
        blocks.append({"type": "divider"})

        # Action buttons
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "✅ Acknowledge",
                        "emoji": True,
                    },
                    "style": "primary",
                    "url": ack_url,
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "📋 View Details",
                        "emoji": True,
                    },
                    "url": detail_url,
                },
            ],
        })

        # Context/footer
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Source: {event.source} | Ticket: {ticket_id[:8]}..." if ticket_id else f"Source: {event.source}",
                },
            ],
        })

        # Fallback text for notifications
        fallback_text = f"{severity_emoji} {title}"

        return {
            "text": fallback_text,
            "blocks": blocks,
        }

    def _build_blocks_from_template(self, blocks_content: list[dict[str, Any]]) -> dict[str, Any]:
        """Build Slack message from pre-rendered template blocks."""
        # Extract fallback text from first text block if available
        fallback_text = "Notification"
        for block in blocks_content:
            if block.get("type") == "header":
                text_obj = block.get("text", {})
                fallback_text = text_obj.get("text", fallback_text)
                break
            elif block.get("type") == "section":
                text_obj = block.get("text", {})
                fallback_text = text_obj.get("text", fallback_text)[:100]
                break

        return {
            "text": fallback_text,
            "blocks": blocks_content,
        }

    async def send(self, event: Event) -> bool:
        """Send notification to Slack via webhook."""
        if not self.enabled:
            logger.warning("Slack channel is not properly configured (missing webhook_url)")
            return False

        # Determine message format based on event content
        message: dict[str, Any]

        # Check if pre-rendered template blocks are available
        if event.meta and event.meta.get(TEMPLATE_BLOCKS_KEY):
            template_blocks = event.meta[TEMPLATE_BLOCKS_KEY]
            if isinstance(template_blocks, list):
                message = self._build_blocks_from_template(template_blocks)
            else:
                logger.warning("Invalid template blocks format, falling back to default")
                message = self._build_ticket_blocks(event)
        # If meta contains ticket_id, use the ticket block format with ack button
        elif event.meta and event.meta.get("ticket_id"):
            message = self._build_ticket_blocks(event)
        else:
            message = self._build_text_message(event)

        headers = {"Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self._webhook_url, headers=headers, json=message)
            response.raise_for_status()

            # Slack webhooks return "ok" as plain text on success
            if response.text != "ok":
                logger.error(f"Slack webhook error: {response.text}")
                return False

            logger.info("Message sent to Slack webhook successfully")
            return True
