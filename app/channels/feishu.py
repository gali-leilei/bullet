"""Feishu (Lark) webhook channel implementation."""

import hashlib
import hmac
import base64
import time
import logging
import json
from datetime import timezone
from typing import Any
from zoneinfo import ZoneInfo
import os

import httpx

from app.channels.base import BaseChannel
from app.models.alert import Alert, AlertGroup
from app.models.event import Event

logger = logging.getLogger(__name__)


# Pre-rendered card from template (passed via event.meta)
TEMPLATE_CARD_KEY = "template_card"


class FeishuChannel(BaseChannel):
    """Feishu webhook bot channel."""

    def __init__(self, webhook_url: str, secret: str | None = None):
        self._webhook_url = webhook_url
        self._secret = secret or ""

    @property
    def name(self) -> str:
        return "feishu"

    @property
    def enabled(self) -> bool:
        return bool(self._webhook_url)

    def _generate_signature(self, timestamp: str) -> str:
        string_to_sign = f"{timestamp}\n{self._secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(hmac_code).decode("utf-8")

    def _get_status_color(self, status: str) -> str:
        return "red" if status == "firing" else "green"

    def _format_alert_element(self, alert: Alert) -> list[dict[str, Any]]:
        elements: list[dict[str, Any]] = []

        status_emoji = "🔴" if alert.is_firing else "🟢"
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"{status_emoji} **{alert.name}**"},
        })

        if alert.summary:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**摘要:** {alert.summary}"},
            })

        if alert.description:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**详情:** {alert.description}"},
            })

        # Convert to local timezone
        local_tz = ZoneInfo(os.environ.get("TZ", "Asia/Shanghai"))
        starts_at = alert.starts_at
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=timezone.utc)
        local_time = starts_at.astimezone(local_tz)
        time_str = local_time.strftime("%Y-%m-%d %H:%M:%S")
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**触发时间:** {time_str}"},
        })

        labels = {k: v for k, v in alert.labels.items() if k != "alertname"}
        if labels:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": "**标签:**"},
            })
            for k, v in labels.items():
                elements.append({
                    "tag": "div",
                    "text": {"tag": "plain_text", "content": f"  • {k}: {v}"},
                })

        if alert.generator_url:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"[查看详情]({alert.generator_url})"},
            })

        return elements

    def _build_card_message(self, alert_group: AlertGroup) -> dict[str, Any]:
        status = alert_group.status
        status_text = "告警触发" if status == "firing" else "告警恢复"
        status_emoji = "🚨" if status == "firing" else "✅"

        # 获取告警规则名作为标题
        alert_name = alert_group.alerts[0].name if alert_group.alerts else "Unknown"

        header = {
            "title": {"tag": "plain_text", "content": f"{status_emoji} {alert_name} - {status_text}"},
            "template": self._get_status_color(status),
        }

        elements: list[dict[str, Any]] = []

        for i, alert in enumerate(alert_group.alerts):
            if i > 0:
                elements.append({"tag": "hr"})
            elements.extend(self._format_alert_element(alert))

        firing_count = len(alert_group.firing_alerts)
        resolved_count = len(alert_group.resolved_alerts)

        elements.append({"tag": "hr"})
        elements.append({
            "tag": "note",
            "elements": [{
                "tag": "plain_text",
                "content": f"来源: {alert_group.source} | 触发: {firing_count} | 恢复: {resolved_count}",
            }],
        })

        return {
            "msg_type": "interactive",
            "card": {"header": header, "elements": elements},
        }

    def _build_text_message(self, event: Event) -> dict[str, Any]:
        payload_json = json.dumps(event.payload, ensure_ascii=False, indent=2, default=str)
        labels_json = json.dumps(event.labels or {}, ensure_ascii=False, default=str)
        text = (
            f"[{(event.source or '').upper()}] {event.type or 'event'}\n"
            f"labels: {labels_json}\n"
            f"payload:\n{payload_json}"
        )
        # Feishu "text" message
        return {"msg_type": "text", "content": {"text": text}}

    def _build_ticket_card(self, event: Event) -> dict[str, Any]:
        """Build a card message for ticket notification with ack link."""
        from app.config import get_settings
        settings = get_settings()

        meta = event.meta or {}
        ticket_id = meta.get("ticket_id", "")
        ack_token = meta.get("ack_token", "")
        title = meta.get("title", "") or event.payload.get("title", "Alert")
        description = meta.get("description", "") or ""
        severity = meta.get("severity", "") or "info"

        # Build ack URL
        ack_url = f"{settings.base_url}/ack/{ticket_id}?token={ack_token}&format=html"

        # Severity color
        color_map = {
            "critical": "red",
            "error": "red",
            "warning": "orange",
            "info": "blue",
        }
        color = color_map.get(severity.lower(), "blue")

        header = {
            "title": {"tag": "plain_text", "content": f"🔔 {title}"},
            "template": color,
        }

        elements: list[dict[str, Any]] = []

        if description:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": description[:500]},
            })

        # Labels
        if event.labels:
            label_text = " | ".join(f"`{k}={v}`" for k, v in list(event.labels.items())[:5])
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**标签:** {label_text}"},
            })

        elements.append({"tag": "hr"})

        # Action button
        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "✅ 确认工单"},
                    "type": "primary",
                    "url": ack_url,
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "📋 查看详情"},
                    "type": "default",
                    "url": f"{settings.base_url}/tickets/{ticket_id}",
                },
            ],
        })

        # Footer
        elements.append({
            "tag": "note",
            "elements": [{
                "tag": "plain_text",
                "content": f"来源: {event.source} | Ticket: {ticket_id[:8]}...",
            }],
        })

        return {
            "msg_type": "interactive",
            "card": {"header": header, "elements": elements},
        }

    def _build_card_from_template(self, card_content: dict[str, Any]) -> dict[str, Any]:
        """Build Feishu message from pre-rendered template card."""
        return {
            "msg_type": "interactive",
            "card": card_content,
        }

    async def send(self, event: Event) -> bool:
        # Determine message format based on event content
        message: dict[str, Any]

        # Check if a pre-rendered template card is available
        if event.meta and event.meta.get(TEMPLATE_CARD_KEY):
            template_card = event.meta[TEMPLATE_CARD_KEY]
            if isinstance(template_card, dict):
                message = self._build_card_from_template(template_card)
            else:
                logger.warning("Invalid template card format, falling back to default")
                message = self._build_ticket_card(event)
        # If meta contains ticket_id, use the ticket card format with ack button
        elif event.meta and event.meta.get("ticket_id"):
            message = self._build_ticket_card(event)
        elif event.type == "alert":
            # If this is an alert event and looks like AlertGroup payload, use rich card
            try:
                alert_group = AlertGroup.model_validate(event.payload)
                message = self._build_card_message(alert_group)
            except Exception:
                message = self._build_text_message(event)
        else:
            message = self._build_text_message(event)

        if self._secret:
            timestamp = str(int(time.time()))
            sign = self._generate_signature(timestamp)
            message["timestamp"] = timestamp
            message["sign"] = sign

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self._webhook_url, json=message)
            response.raise_for_status()

            result = response.json()
            if result.get("code") != 0:
                logger.error(f"Feishu API error: {result}")
                return False

            logger.info("Alert sent to Feishu successfully")
            return True

