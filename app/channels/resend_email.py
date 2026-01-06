"""Resend email channel implementation.

Channel should be transport-only: it accepts a payload (here it's the unified AlertGroup)
and renders it via Jinja template, without hard-coding any source-specific semantics.

Resend REST API:
POST https://api.resend.com/emails
Authorization: Bearer re_xxx
"""

import json
import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, Template, select_autoescape

import httpx

from app.channels.base import BaseChannel
from app.models.event import Event

logger = logging.getLogger(__name__)


def _default_template_path() -> Path:
    # app/channels/resend_email.py -> app/templates/resend_email.html.j2
    return Path(__file__).resolve().parents[1] / "templates" / "resend_email.html.j2"


def _build_render_context(event: Event) -> dict[str, Any]:
    event_dict = event.model_dump()
    title = f"[{(event.source or '').upper()}] {event.type or 'event'}"

    payload_json = json.dumps(event_dict, ensure_ascii=False, indent=2, default=str)

    # Convenience shortcuts for templates (still generic).
    payload = event_dict.get("payload") or {}
    labels = event_dict.get("labels") or {}

    return {
        "title": title,
        "event": event_dict,
        "payload": payload,
        "labels": labels,
        "payload_json": payload_json,
    }


def _load_template_from_path(path: Path) -> Template:
    env = Environment(
        loader=FileSystemLoader(str(path.parent)),
        autoescape=select_autoescape(["html", "htm", "xml", "j2"]),
    )
    return env.get_template(path.name)


class ResendEmailChannel(BaseChannel):
    """Send alerts via Resend email API."""

    def __init__(
        self,
        *,
        api_key: str,
        from_email: str,
        to: list[str],
        subject_prefix: str = "",
        subject_template: str = "",
        template_path: str = "",
        reply_to: str | None = None,
        api_url: str = "https://api.resend.com/emails",
        timeout_s: float = 30.0,
        name: str = "",
        subject_override: str | None = None,
        body_override: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._from_email = from_email
        self._to = to
        self._subject_prefix = subject_prefix
        self._subject_template = subject_template
        self._reply_to = reply_to
        self._api_url = api_url
        self._timeout_s = timeout_s
        self._name_override = name.strip()
        self._subject_override = subject_override
        self._body_override = body_override

        resolved_template_path = Path(template_path) if template_path else _default_template_path()
        self._html_template = _load_template_from_path(resolved_template_path)

    @property
    def name(self) -> str:
        return self._name_override or "resend_email"

    @property
    def enabled(self) -> bool:
        return bool(self._api_key and self._from_email and self._to)

    def _render_subject(self, ctx: dict[str, Any]) -> str:
        if self._subject_template:
            # Subject should not be HTML-escaped; use a dedicated env without autoescape.
            env = Environment(autoescape=False)
            return env.from_string(self._subject_template).render(**ctx).strip()
        return ctx.get("title", "notification")

    async def send(self, event: Event) -> bool:
        # Use template-rendered content if provided, otherwise use default rendering
        if self._subject_override and self._body_override:
            subject = f"{self._subject_prefix}{self._subject_override}"
            html_body = self._body_override
        else:
            ctx = _build_render_context(event)
            subject = f"{self._subject_prefix}{self._render_subject(ctx)}"
            html_body = self._html_template.render(**ctx)

        payload: dict[str, Any] = {
            "from": self._from_email,
            "to": self._to,
            "subject": subject,
            "html": html_body,
        }
        if self._reply_to:
            # Resend docs show `reply_to` (snake) in REST examples.
            payload["reply_to"] = self._reply_to

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            resp = await client.post(self._api_url, headers=headers, json=payload)
            if resp.status_code >= 400:
                logger.error(
                    "Resend API error: status=%s body=%s",
                    resp.status_code,
                    resp.text,
                )
                resp.raise_for_status()

            data = resp.json()
            logger.info("Alert sent via Resend: %s", data)
            return True


