"""Alert routing based on source and labels."""

import logging
from pathlib import Path
from typing import Any

import yaml

from app.channels.base import BaseChannel
from app.channels.feishu import FeishuChannel
from app.channels.resend_email import ResendEmailChannel
from app.channels.slack import SlackWebhookChannel, SlackBotChannel
from app.config import get_settings
from app.models.alert import AlertGroup
from app.models.event import Event
from app.models.routes import ChannelConfig, Route, RoutesConfig

logger = logging.getLogger(__name__)


def load_routes_config(config_path: str | Path) -> RoutesConfig:
    """Load routing configuration from YAML file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Routes config not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return RoutesConfig.model_validate(data)


def create_channel_from_config(config: ChannelConfig) -> BaseChannel:
    """Create a channel instance from configuration."""
    if config.type == "feishu":
        return FeishuChannel(
            webhook_url=config.webhook_url,
            secret=config.secret or None,
        )
    elif config.type == "resend_email":
        settings = get_settings()
        api_key = config.api_key or getattr(settings, "resend_api_key", "")
        from_email = config.from_email or getattr(settings, "resend_from_email", "")
        reply_to = config.reply_to or None
        api_url = getattr(settings, "resend_api_url", "https://api.resend.com/emails")
        return ResendEmailChannel(
            api_key=api_key,
            from_email=from_email,
            to=config.to,
            subject_prefix=config.subject_prefix,
            subject_template=config.subject_template,
            template_path=config.template_path,
            reply_to=reply_to,
            api_url=api_url,
            name=config.name,
        )
    elif config.type == "slack-webhook":
        return SlackWebhookChannel(
            webhook_url=config.webhook_url,
        )
    elif config.type == "slack-bot":
        return SlackBotChannel(
            bot_token=config.bot_token,
            channel_id=config.channel_id,
        )
    else:
        raise ValueError(f"Unknown channel type: {config.type}")


class AlertRouter:
    """Routes alerts to appropriate channels based on source and labels."""

    def __init__(self, config: RoutesConfig):
        self._config = config
        self._route_channels: dict[str, list[BaseChannel]] = {}

        for i, route in enumerate(config.routes):
            route_key = route.name or f"route_{i}"
            self._route_channels[route_key] = [
                create_channel_from_config(ch_config)
                for ch_config in route.channels
            ]

        logger.info(f"Router initialized with {len(config.routes)} route(s)")

    @property
    def routes(self) -> list[Route]:
        return self._config.routes

    def find_route(self, event: Event) -> tuple[Route | None, list[BaseChannel]]:
        """Find matching route and channels for event."""
        source = event.source
        labels = event.labels

        logger.debug(f"Matching source={source}, labels={labels}")

        for i, route in enumerate(self._config.routes):
            if route.matches(source, labels):
                route_key = route.name or f"route_{i}"
                channels = self._route_channels.get(route_key, [])
                logger.info(f"Matched route '{route_key}' with {len(channels)} channel(s)")
                return route, channels

        logger.info("No matching route found, alert will be discarded")
        return None, []

    def _wrap_alert_group(self, alert_group: AlertGroup) -> Event:
        # Alerts are one scenario; wrap into generic Event for channel delivery.
        payload: dict[str, Any] = alert_group.model_dump()
        return Event(
            source=alert_group.source,
            type="alert",
            labels=alert_group.labels,
            payload=payload,
            meta={"raw": alert_group.raw},
        )

    async def route_event(self, event: Event) -> dict[str, bool]:
        """Route a generic event to matching channels."""
        route, channels = self.find_route(event)

        if not route or not channels:
            return {}

        results: dict[str, bool] = {}
        for channel in channels:
            success = await channel.send_safe(event)
            results[channel.name] = success

            if success:
                logger.info(f"Alert sent to {channel.name}")
            else:
                logger.error(f"Failed to send alert to {channel.name}")

        return results

    async def route_alert(self, alert_group: AlertGroup) -> dict[str, bool]:
        """Backward-compatible alert routing (wraps alert group into Event)."""
        return await self.route_event(self._wrap_alert_group(alert_group))

