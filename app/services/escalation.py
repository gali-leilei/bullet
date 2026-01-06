"""Escalation service - handles ticket escalation based on project configuration."""

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from beanie.operators import In

from app.config import get_settings
from app.models.notification_group import NotificationGroup
from app.models.project import Project
from app.models.ticket import EventType, Ticket, TicketStatus
from app.services.notification import NotificationService

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: AsyncIOScheduler | None = None


async def check_and_escalate_tickets() -> None:
    """Check all pending tickets and escalate or repeat notify if needed.

    This function is called periodically by the scheduler.
    """
    logger.debug("Running escalation check...")

    # Find all projects with escalation enabled
    projects = await Project.find(
        Project.escalation_config.enabled == True,  # noqa: E712
        Project.is_active == True,  # noqa: E712
    ).to_list()

    for project in projects:
        # Skip silenced projects
        if project.is_silenced():
            logger.debug(f"Project {project.id} is silenced, skipping escalation check")
            continue
        await _check_project_tickets(project)


async def _check_project_tickets(project: Project) -> None:
    """Check tickets for a single project and escalate or repeat notify if needed.
    
    Escalation is based on the ordered list project.notification_group_ids.
    escalation_level 1 = index 0 (first group)
    escalation_level 2 = index 1 (second group)
    ...
    
    Before escalating, if the current notification group has repeat_interval set,
    we will repeat the notification at that interval until escalation timeout.
    """
    config = project.escalation_config
    escalation_timeout = timedelta(minutes=config.timeout_minutes)
    now = datetime.utcnow()

    # Find pending or escalated tickets that haven't been acknowledged
    tickets = await Ticket.find(
        Ticket.project_id == str(project.id),
        In(Ticket.status, [TicketStatus.PENDING, TicketStatus.ESCALATED]),
    ).to_list()

    # Max escalation level is determined by number of bound notification groups
    max_level = len(project.notification_group_ids)

    for ticket in tickets:
        await _process_ticket(ticket, project, escalation_timeout, max_level, now)


async def _process_ticket(
    ticket: Ticket,
    project: Project,
    escalation_timeout: timedelta,
    max_level: int,
    now: datetime,
) -> None:
    """Process a single ticket for repeat notification or escalation.
    
    Note: Only tickets with severity='critical' can be escalated.
    Non-critical tickets will only receive repeat notifications if configured.
    """
    # Check if ticket can be escalated (must have severity=critical)
    if not ticket.can_escalate():
        logger.debug(
            f"Ticket {ticket.id} cannot escalate (severity={ticket.severity}, "
            f"only 'critical' severity tickets can escalate)"
        )
        return

    # Get current notification group
    current_index = ticket.escalation_level - 1  # 0-indexed
    if current_index >= len(project.notification_group_ids):
        return

    current_group_id = project.notification_group_ids[current_index]
    current_group = await NotificationGroup.get(current_group_id)

    if not current_group:
        logger.warning(f"Current notification group {current_group_id} not found for ticket {ticket.id}")
        return

    # Calculate time since last notification
    if ticket.last_notified_at:
        time_since_notification = now - ticket.last_notified_at
    else:
        time_since_notification = now - ticket.created_at

    # Check for repeat notification first (if configured and not yet time to escalate)
    if current_group.repeat_interval and time_since_notification < escalation_timeout:
        repeat_interval = timedelta(minutes=current_group.repeat_interval)
        if time_since_notification >= repeat_interval:
            # Time to repeat notification
            await _repeat_notification(ticket, current_group, project)
            return

    # Check if it's time to escalate
    if time_since_notification < escalation_timeout:
        return  # Not yet timed out for escalation

    # Check if we can escalate further
    if ticket.escalation_level >= max_level:
        # Already at max level, check for repeat at final level
        if current_group.repeat_interval:
            repeat_interval = timedelta(minutes=current_group.repeat_interval)
            if time_since_notification >= repeat_interval:
                await _repeat_notification(ticket, current_group, project)
        else:
            # Check if we need to record max level reached event (only once)
            has_max_event = any(e.type == EventType.MAX_LEVEL_REACHED for e in ticket.events)
            if not has_max_event:
                ticket.add_event(
                    EventType.MAX_LEVEL_REACHED,
                    level=ticket.escalation_level,
                    group_name=current_group.name,
                    details="已到达最高级别，无更多通知组",
                )
                ticket.updated_at = datetime.utcnow()
                await ticket.save()
                logger.debug(f"Ticket {ticket.id} at max level ({ticket.escalation_level}/{max_level}), no repeat configured")
        return

    # Get next notification group
    next_level = ticket.escalation_level + 1
    next_index = next_level - 1

    if next_index >= len(project.notification_group_ids):
        logger.debug(f"No notification group at level {next_level} for project {project.id}")
        return

    next_group_id = project.notification_group_ids[next_index]
    next_group = await NotificationGroup.get(next_group_id)

    if not next_group:
        logger.warning(f"Notification group {next_group_id} not found (level {next_level})")
        return

    # Escalate the ticket
    await _escalate_ticket(ticket, next_level, next_group, project)


async def _repeat_notification(ticket: Ticket, group: NotificationGroup, project: Project) -> None:
    """Send a repeat notification to the current notification group."""
    logger.info(f"Repeating notification for ticket {ticket.id} to group {group.name}")

    # Get template for project
    from app.services.template import TemplateService
    template = await TemplateService.get_template_for_project(project)

    # Send notification with repeat flag
    results = await NotificationService.send_to_group(
        ticket, group, template=template, project=project, is_repeated=True
    )

    # Determine success
    success = any(results.values()) if results else False

    # Add event
    ticket.add_event(
        EventType.REPEATED,
        level=ticket.escalation_level,
        group_name=group.name,
        success=success,
        details=f"重复通知结果: {results}" if results else "无渠道配置",
    )

    # Update notification tracking
    ticket.last_notified_at = datetime.utcnow()
    ticket.notification_count += 1
    ticket.updated_at = datetime.utcnow()
    await ticket.save()

    logger.info(f"Ticket {ticket.id} repeat notification sent, results: {results}")


async def _escalate_ticket(ticket: Ticket, new_level: int, group: NotificationGroup, project: Project) -> None:
    """Escalate a ticket to the next notification group level."""
    logger.info(f"Escalating ticket {ticket.id} to level {new_level} (group: {group.name})")

    # Update ticket status and level first (so template sees the new level)
    ticket.status = TicketStatus.ESCALATED
    ticket.escalation_level = new_level
    ticket.updated_at = datetime.utcnow()

    # Get template for project
    from app.services.template import TemplateService
    template = await TemplateService.get_template_for_project(project)

    # Send notification with escalation flag
    results = await NotificationService.send_to_group(
        ticket, group, template=template, project=project, is_escalated=True
    )

    # Determine success
    success = any(results.values()) if results else False

    # Add escalation event
    ticket.add_event(
        EventType.ESCALATED,
        level=new_level,
        group_name=group.name,
        success=success,
        details=f"升级通知结果: {results}" if results else "无渠道配置",
    )

    # Update notification tracking
    ticket.last_notified_at = datetime.utcnow()
    ticket.notification_count += 1
    await ticket.save()

    logger.info(f"Ticket {ticket.id} escalated to level {new_level}, results: {results}")


def start_scheduler() -> AsyncIOScheduler:
    """Start the escalation scheduler."""
    global _scheduler

    if _scheduler is not None:
        return _scheduler

    settings = get_settings()
    interval = settings.escalation_check_interval

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        check_and_escalate_tickets,
        "interval",
        seconds=interval,
        id="escalation_check",
        name="Check and escalate tickets",
        replace_existing=True,
    )
    _scheduler.start()

    logger.info(f"Escalation scheduler started (interval: {interval}s)")
    return _scheduler


def stop_scheduler() -> None:
    """Stop the escalation scheduler."""
    global _scheduler

    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Escalation scheduler stopped")
