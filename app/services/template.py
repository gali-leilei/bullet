"""Template rendering service for notifications."""

import json
import logging
from typing import Any, Optional

from jinja2 import BaseLoader, Environment, TemplateSyntaxError

from app.config import get_settings
from app.models.notification_template import BUILTIN_TEMPLATES, NotificationTemplate
from app.models.project import Project
from app.models.ticket import Ticket

logger = logging.getLogger(__name__)


def _json_escape(value: Any) -> str:
    """Escape a value for safe use inside a JSON string literal.
    
    This is used when the value will be embedded inside a JSON string,
    not as a standalone JSON value. It escapes special characters like
    newlines, quotes, and backslashes.
    """
    if value is None:
        return ""
    s = str(value)
    # Use json.dumps to properly escape, then strip the surrounding quotes
    escaped = json.dumps(s)
    # Remove the surrounding quotes that json.dumps adds
    return escaped[1:-1]


# Create a Jinja2 environment for template rendering
_jinja_env = Environment(loader=BaseLoader(), autoescape=False)
# Add custom filters
_jinja_env.filters["json_escape"] = _json_escape
_jinja_env.filters["je"] = _json_escape  # Short alias


class TemplateService:
    """Service for rendering notification templates."""

    @staticmethod
    def build_context(
        ticket: Ticket,
        project: Optional[Project] = None,
        is_escalated: bool = False,
        is_repeated: bool = False,
        notification_count: Optional[int] = None,
        is_ack_notification: bool = False,
        acknowledged_by_name: str = "",
    ) -> dict[str, Any]:
        """Build template context from ticket and project.

        Available variables in templates:
        - ticket: Ticket data as dict
        - payload: Raw webhook payload
        - parsed: Parsed data from source parser
        - source: Source type string
        - ack_url: Acknowledgement callback URL
        - detail_url: Ticket detail page URL
        - project: Project data as dict (if available)
        - is_escalated: Whether this is an escalation notification
        - is_repeated: Whether this is a repeat notification
        - notification_count: Current notification count (1-based)
        - notification_label: Human-readable label like "第3次通知" or "已升级"
        - is_ack_notification: Whether this is an acknowledgement notification
        - acknowledged_by_name: Name of the person who acknowledged
        """
        settings = get_settings()
        base_url = settings.base_url.rstrip("/")

        # Use provided notification_count or fall back to ticket's count + 1 (for new notification)
        count = notification_count if notification_count is not None else (ticket.notification_count + 1)

        # Build ticket dict, handling potential serialization issues
        ticket_dict = {
            "id": str(ticket.id),
            "title": ticket.title,
            "description": ticket.description,
            "severity": ticket.severity,
            "source": ticket.source,
            "status": ticket.status.value if ticket.status else "",
            "labels": ticket.labels,
            "escalation_level": ticket.escalation_level,
            "notification_count": count,
            "created_at": ticket.created_at.isoformat() if ticket.created_at else "",
        }

        # Build notification label
        notification_label = ""
        if is_ack_notification:
            notification_label = f"已确认 by {acknowledged_by_name}" if acknowledged_by_name else "已确认"
        elif is_escalated:
            notification_label = f"已升级到 L{ticket.escalation_level}"
        elif is_repeated:
            notification_label = f"第{count}次通知"
        elif count > 1:
            notification_label = f"第{count}次通知"

        context = {
            "ticket": ticket_dict,
            "payload": ticket.payload or {},
            "parsed": ticket.parsed_data or {},
            "source": ticket.source,
            "ack_url": f"{base_url}/ack/{ticket.id}?token={ticket.ack_token}",
            "detail_url": f"{base_url}/tickets/{ticket.id}",
            # Notification metadata
            "is_escalated": is_escalated,
            "is_repeated": is_repeated,
            "notification_count": count,
            "notification_label": notification_label,
            "is_ack_notification": is_ack_notification,
            "acknowledged_by_name": acknowledged_by_name,
        }

        if project:
            context["project"] = {
                "id": str(project.id),
                "name": project.name,
                "description": project.description,
            }

        return context

    @staticmethod
    def render_string(template_str: str, context: dict[str, Any]) -> str:
        """Render a Jinja2 template string with the given context.

        Returns empty string if template is empty or rendering fails.
        """
        if not template_str:
            return ""

        try:
            template = _jinja_env.from_string(template_str)
            return template.render(**context)
        except TemplateSyntaxError as e:
            logger.error(f"Template syntax error: {e}")
            return ""
        except Exception as e:
            logger.error(f"Template rendering error: {e}")
            return ""

    @staticmethod
    def render_feishu_card(
        template: NotificationTemplate, context: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Render Feishu card template and parse as JSON.

        Returns None if template is empty or rendering/parsing fails.
        """
        if not template.feishu_card:
            return None

        try:
            rendered = TemplateService.render_string(template.feishu_card, context)
            if not rendered:
                return None
            return json.loads(rendered)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse rendered Feishu card as JSON: {e}")
            return None

    @staticmethod
    def render_email(
        template: NotificationTemplate, context: dict[str, Any]
    ) -> tuple[str, str]:
        """Render email subject and body templates.

        Returns tuple of (subject, body). Empty strings if templates are empty.
        """
        subject = TemplateService.render_string(template.email_subject, context)
        body = TemplateService.render_string(template.email_body, context)
        return subject, body

    @staticmethod
    def render_sms(template: NotificationTemplate, context: dict[str, Any]) -> str:
        """Render SMS message template.

        Returns empty string if template is empty.
        """
        return TemplateService.render_string(template.sms_message, context)

    @staticmethod
    async def get_template_for_project(project: Project) -> NotificationTemplate:
        """Get the notification template for a project.

        Returns the project's configured template, or the default template.
        """
        # Try to get project's configured template
        if project.notification_template_id:
            template = await NotificationTemplate.get(project.notification_template_id)
            if template:
                return template
            logger.warning(
                f"Template {project.notification_template_id} not found for project {project.id}, using default"
            )

        # Fall back to default template
        default_template = await NotificationTemplate.find_one(
            NotificationTemplate.name == "default"
        )
        if default_template:
            return default_template

        # If no default template exists (shouldn't happen), create a minimal one in memory
        logger.warning("No default template found, using minimal fallback")
        return NotificationTemplate(
            name="fallback",
            description="Fallback template",
            is_builtin=False,
        )

    @staticmethod
    async def ensure_builtin_templates() -> None:
        """Ensure built-in templates exist in database.

        Called during application startup.
        """
        for name, template_data in BUILTIN_TEMPLATES.items():
            existing = await NotificationTemplate.find_one(
                NotificationTemplate.name == name
            )
            if existing:
                # Update existing built-in template
                if existing.is_builtin:
                    existing.description = template_data["description"]
                    existing.feishu_card = template_data["feishu_card"]
                    existing.email_subject = template_data["email_subject"]
                    existing.email_body = template_data["email_body"]
                    existing.sms_message = template_data["sms_message"]
                    await existing.save()
                    logger.debug(f"Updated built-in template: {name}")
            else:
                # Create new built-in template
                template = NotificationTemplate(**template_data)
                await template.insert()
                logger.info(f"Created built-in template: {name}")

