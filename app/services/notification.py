"""Notification service - sends notifications through configured channels."""

import logging
from typing import Any, List, Optional

from bson import ObjectId

from app.channels.feishu import FeishuChannel, TEMPLATE_CARD_KEY
from app.channels.resend_email import ResendEmailChannel
from app.channels.slack import SlackChannel
from app.channels.twilio_sms import TwilioSMSChannel
from app.config import get_settings
from app.models.contact import Contact
from app.models.event import Event
from app.models.notification_group import ChannelConfig, ChannelType, NotificationGroup
from app.models.notification_template import NotificationTemplate
from app.models.project import Project
from app.models.ticket import Ticket
from app.services.template import TemplateService

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending notifications to configured channels."""

    @staticmethod
    async def send_to_group(
        ticket: Ticket,
        group: NotificationGroup,
        template: Optional[NotificationTemplate] = None,
        project: Optional[Project] = None,
        is_escalated: bool = False,
        is_repeated: bool = False,
        is_ack_notification: bool = False,
        acknowledged_by_name: str = "",
    ) -> dict[str, bool]:
        """Send notification to all channels in a notification group.

        Args:
            ticket: The ticket to notify about
            group: The notification group to send to
            template: Optional template for rendering messages
            project: Optional project for template context
            is_escalated: Whether this is an escalation notification
            is_repeated: Whether this is a repeat notification
            is_ack_notification: Whether this is an acknowledgement notification
            acknowledged_by_name: Name of the person who acknowledged

        Returns a dict of channel_name -> success status.
        """
        results: dict[str, bool] = {}

        # Build template context if template is provided
        template_context: Optional[dict[str, Any]] = None
        rendered_feishu_card: Optional[dict[str, Any]] = None
        rendered_email: Optional[tuple[str, str]] = None
        rendered_sms: Optional[str] = None

        if template:
            # For repeat/escalate, the count will be incremented after sending
            # So we pass the next count (current + 1)
            next_count = ticket.notification_count + 1
            template_context = TemplateService.build_context(
                ticket,
                project,
                is_escalated=is_escalated,
                is_repeated=is_repeated,
                notification_count=next_count,
                is_ack_notification=is_ack_notification,
                acknowledged_by_name=acknowledged_by_name,
            )
            rendered_feishu_card = TemplateService.render_feishu_card(template, template_context)
            rendered_email = TemplateService.render_email(template, template_context)
            rendered_sms = TemplateService.render_sms(template, template_context)

        # Create event from ticket with template data
        meta: dict[str, Any] = {
            "ticket_id": str(ticket.id),
            "ack_token": ticket.ack_token,
            "title": ticket.title,
            "description": ticket.description,
            "severity": ticket.severity,
        }

        # Add rendered template card if available
        if rendered_feishu_card:
            meta[TEMPLATE_CARD_KEY] = rendered_feishu_card

        event = Event(
            source=ticket.source,
            type="notification",
            labels=ticket.labels,
            payload=ticket.payload,
            meta=meta,
        )

        for config in group.channel_configs:
            channel_results = await NotificationService._send_to_channel_config(
                event, config, rendered_email=rendered_email, rendered_sms=rendered_sms
            )
            results.update(channel_results)

        return results

    @staticmethod
    async def _send_to_channel_config(
        event: Event,
        config: ChannelConfig,
        rendered_email: Optional[tuple[str, str]] = None,
        rendered_sms: Optional[str] = None,
    ) -> dict[str, bool]:
        """Send notification through a channel config to all its contacts.

        Args:
            event: The event to send
            config: Channel configuration
            rendered_email: Optional pre-rendered (subject, body) tuple
            rendered_sms: Optional pre-rendered SMS message
        """
        results: dict[str, bool] = {}

        # Fetch contacts by string IDs
        contact_object_ids = [ObjectId(cid) for cid in config.contact_ids if cid]
        contacts = await Contact.find({"_id": {"$in": contact_object_ids}}).to_list()

        if not contacts:
            logger.warning(f"No contacts found for channel config: {config.type}")
            return results

        settings = get_settings()

        if config.type == ChannelType.FEISHU:
            for contact in contacts:
                if contact.feishu_webhook_url:
                    channel = FeishuChannel(webhook_url=contact.feishu_webhook_url)
                    success = await channel.send_safe(event)
                    results[f"feishu:{contact.name}"] = success
                else:
                    logger.warning(f"Contact {contact.name} has no feishu_webhook_url")

        elif config.type == ChannelType.EMAIL:
            # Collect all emails from contacts
            all_emails: List[str] = []
            for contact in contacts:
                all_emails.extend(contact.emails)

            if all_emails:
                # Use rendered email if available
                subject = None
                body = None
                if rendered_email and rendered_email[0] and rendered_email[1]:
                    subject, body = rendered_email

                channel = ResendEmailChannel(
                    api_key=settings.resend_api_key,
                    from_email=settings.resend_from_email,
                    to=all_emails,
                    subject_override=subject,
                    body_override=body,
                )
                success = await channel.send_safe(event)
                results["email"] = success
            else:
                logger.warning("No email addresses found in contacts")

        elif config.type == ChannelType.SMS:
            # Collect all phones from contacts
            all_phones: List[str] = []
            for contact in contacts:
                all_phones.extend(contact.phones)

            if all_phones:
                # Use rendered SMS if available
                channel = TwilioSMSChannel(
                    to_numbers=all_phones,
                    message_override=rendered_sms if rendered_sms else None,
                )
                success = await channel.send_safe(event)
                results["sms"] = success
            else:
                logger.warning("No phone numbers found in contacts")

        elif config.type == ChannelType.SLACK:
            for contact in contacts:
                if contact.slack_channel_id:
                    channel = SlackChannel(channel_id=contact.slack_channel_id)
                    success = await channel.send_safe(event)
                    results[f"slack:{contact.name}"] = success
                else:
                    logger.warning(f"Contact {contact.name} has no slack_channel_id")

        return results

    @staticmethod
    async def notify_ticket(ticket: Ticket, escalation_level: int = 1) -> dict[str, bool]:
        """Send notification for a ticket at the given escalation level.

        escalation_level 1 = first group (index 0)
        escalation_level 2 = second group (index 1)
        ...
        """
        # Get project to access notification_group_ids
        project = await Project.get(ticket.project_id)
        if not project:
            logger.warning(f"Project not found: {ticket.project_id}")
            return {}

        if not project.notification_group_ids:
            logger.warning(f"Project {project.id} has no notification groups configured")
            return {}

        # Get notification group by index
        group_index = escalation_level - 1  # 0-indexed
        if group_index >= len(project.notification_group_ids):
            logger.warning(f"Escalation level {escalation_level} exceeds available groups for project {project.id}")
            return {}

        group_id = project.notification_group_ids[group_index]
        group = await NotificationGroup.get(group_id)

        if not group:
            logger.warning(f"Notification group {group_id} not found for project {ticket.project_id} at level {escalation_level}")
            return {}

        # Get template for project
        template = await TemplateService.get_template_for_project(project)

        logger.info(f"Sending notification for ticket {ticket.id} to group {group.name} (level {escalation_level}) using template {template.name}")
        return await NotificationService.send_to_group(ticket, group, template=template, project=project)

    @staticmethod
    async def notify_ticket_acknowledged(
        ticket: Ticket,
        acknowledged_by_name: str,
    ) -> dict[str, bool]:
        """Send acknowledgement notification to all notification groups that have been notified.

        This sends to all groups from level 1 to the current escalation_level.

        Args:
            ticket: The acknowledged ticket
            acknowledged_by_name: Name of the person who acknowledged

        Returns a dict of channel_name -> success status.
        """
        # Get project to access notification_group_ids
        project = await Project.get(ticket.project_id)
        if not project:
            logger.warning(f"Project not found: {ticket.project_id}")
            return {}

        # Check if notify_on_ack is enabled
        if not project.notify_on_ack:
            logger.debug(f"Project {project.id} has notify_on_ack disabled, skipping ack notification")
            return {}

        if not project.notification_group_ids:
            logger.warning(f"Project {project.id} has no notification groups configured")
            return {}

        # Get template for project
        template = await TemplateService.get_template_for_project(project)

        all_results: dict[str, bool] = {}

        # Send to all groups from level 1 to current escalation level
        for level in range(1, ticket.escalation_level + 1):
            group_index = level - 1
            if group_index >= len(project.notification_group_ids):
                break

            group_id = project.notification_group_ids[group_index]
            group = await NotificationGroup.get(group_id)

            if not group:
                logger.warning(f"Notification group {group_id} not found for ack notification")
                continue

            logger.info(f"Sending ack notification for ticket {ticket.id} to group {group.name} (level {level})")
            results = await NotificationService.send_to_group(
                ticket,
                group,
                template=template,
                project=project,
                is_ack_notification=True,
                acknowledged_by_name=acknowledged_by_name,
            )
            # Prefix results with level to avoid key conflicts
            for key, value in results.items():
                all_results[f"L{level}:{key}"] = value

        return all_results
