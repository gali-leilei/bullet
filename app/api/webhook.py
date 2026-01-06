"""Webhook API for receiving alerts and creating tickets."""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from app.models.namespace import Namespace
from app.models.notification_group import NotificationGroup
from app.models.project import Project
from app.models.ticket import EventType, Ticket, TicketStatus
from app.services.notification import NotificationService
from app.sources.base import BaseSource
from app.sources.grafana import GrafanaSource

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])

# Source parsers registry
_sources: dict[str, BaseSource] = {}


def get_sources() -> dict[str, BaseSource]:
    """Get or initialize source parsers."""
    if not _sources:
        _sources["grafana"] = GrafanaSource()
        # Add more sources here as needed
    return _sources


def _extract_ticket_info(source_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Extract title, description, severity, labels, and parsed_data from payload.

    Returns a dict with:
    - title: str
    - description: str
    - severity: str
    - labels: dict
    - status: str
    - parsed_data: Optional[dict] - structured data from source parser
    """
    sources = get_sources()
    source = sources.get(source_name)

    if source:
        try:
            alert_group = source.parse(payload)
            # Convert parsed result to dict for template rendering
            parsed_data = alert_group.model_dump()

            # Get info from first alert
            if alert_group.alerts:
                alert = alert_group.alerts[0]
                return {
                    "title": alert.name or alert.summary,
                    "description": alert.description,
                    "severity": alert.severity,
                    "labels": {**alert_group.labels, **alert.labels},
                    "status": alert_group.status,
                    "parsed_data": parsed_data,
                }
            return {
                "title": "",
                "description": "",
                "severity": "",
                "labels": alert_group.labels,
                "status": alert_group.status,
                "parsed_data": parsed_data,
            }
        except Exception as e:
            logger.warning(f"Failed to parse payload with {source_name} parser: {e}")

    # Fallback: try to extract common fields
    return {
        "title": payload.get("title", payload.get("alertname", payload.get("name", ""))),
        "description": payload.get("message", payload.get("description", "")),
        "severity": payload.get("severity", payload.get("level", "")),
        "labels": payload.get("labels", {}),
        "status": payload.get("status", "firing"),
        "parsed_data": None,
    }


@router.post("/{namespace_slug}/{project_id}")
async def receive_webhook(
    namespace_slug: str,
    project_id: str,
    request: Request,
    source: str = Query(default="custom", description="Source type (grafana, alertmanager, custom)"),
) -> JSONResponse:
    """Receive webhook and create ticket.

    URL format: /webhook/{namespace_slug}/{project_id}?source=grafana
    """
    # Find namespace by slug
    namespace = await Namespace.find_one(Namespace.slug == namespace_slug)
    if not namespace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Namespace not found: {namespace_slug}",
        )

    # Find project
    project = await Project.get(project_id)
    if not project or project.namespace_id != str(namespace.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project not found: {project_id}",
        )

    if not project.is_active:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "ignored",
                "message": "Project is disabled",
            },
        )

    # Parse payload
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON payload: {e}",
        )

    logger.info(f"Received webhook for {namespace_slug}/{project_id} from {source}")

    # Extract ticket info
    info = _extract_ticket_info(source, payload)

    # Check if this is a "resolved" status - if so, try to resolve existing tickets
    if info.get("status") == "resolved":
        # Find pending tickets for this project and resolve them
        pending_tickets = await Ticket.find(
            Ticket.project_id == str(project.id),
            Ticket.status == TicketStatus.PENDING,
        ).to_list()

        for t in pending_tickets:
            t.status = TicketStatus.RESOLVED
            t.resolved_at = datetime.utcnow()
            t.updated_at = datetime.utcnow()
            t.add_event(EventType.RESOLVED, details="自动解决（收到 resolved 状态）")
            await t.save()

        if pending_tickets:
            logger.info(f"Resolved {len(pending_tickets)} pending tickets for project {project_id}")

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "resolved",
                "message": f"Resolved {len(pending_tickets)} ticket(s)",
                "source": source,
            },
        )

    # Create ticket (always create, even if silenced)
    ticket = Ticket(
        project_id=str(project.id),
        source=source,
        status=TicketStatus.PENDING,
        escalation_level=1,
        payload=payload,
        parsed_data=info.get("parsed_data"),
        labels=info.get("labels", {}),
        title=info.get("title", ""),
        description=info.get("description", ""),
        severity=info.get("severity", ""),
    )
    # Add created event
    ticket.add_event(EventType.CREATED, details=f"来源: {source}")

    # Check if project is silenced
    if project.is_silenced():
        ticket.add_event(EventType.NOTIFIED_SILENCED, level=1, details="项目已静默，跳过通知")
        await ticket.insert()

        logger.info(f"Created ticket {ticket.id} for project {project_id} (silenced)")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "silenced",
                "message": "Ticket created but notifications silenced",
                "ticket_id": str(ticket.id),
                "source": source,
            },
        )

    await ticket.insert()
    logger.info(f"Created ticket {ticket.id} for project {project_id}")

    # Get first notification group name for event
    group_name = None
    if project.notification_group_ids:
        first_group = await NotificationGroup.get(project.notification_group_ids[0])
        if first_group:
            group_name = first_group.name

    # Send notification to first notification group
    results = await NotificationService.notify_ticket(ticket, escalation_level=1)

    # Determine if notification was successful
    success = any(results.values()) if results else False

    # Add notification event
    ticket.add_event(
        EventType.NOTIFIED,
        level=1,
        group_name=group_name,
        success=success,
        details=f"通知结果: {results}" if results else "无通知组配置",
    )

    # Update ticket notification info
    ticket.last_notified_at = datetime.utcnow()
    ticket.notification_count = 1
    await ticket.save()

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "ok",
            "message": "Ticket created",
            "ticket_id": str(ticket.id),
            "source": source,
            "notification_results": results,
        },
    )
