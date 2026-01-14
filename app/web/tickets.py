"""Ticket management routes."""

import logging
from datetime import datetime
from typing import Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import CurrentUser
from app.models.namespace import Namespace
from app.models.project import Project
from app.models.ticket import EventType, Ticket, TicketStatus
from app.models.user import User
from app.services.notification import NotificationService
from app.web.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.get("/", response_class=HTMLResponse)
async def list_tickets(
    request: Request,
    user: CurrentUser,
    project_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """List tickets with filtering and pagination."""
    # Build query
    query = {}

    if project_id:
        query["project_id"] = project_id

    if status_filter and status_filter != "all":
        try:
            query["status"] = TicketStatus(status_filter)
        except ValueError:
            pass

    # Execute query with pagination
    skip = (page - 1) * per_page

    if search:
        # Search in title, description, source
        tickets_query = Ticket.find(
            query,
            {"$or": [
                {"title": {"$regex": search, "$options": "i"}},
                {"description": {"$regex": search, "$options": "i"}},
                {"source": {"$regex": search, "$options": "i"}},
            ]}
        )
    else:
        tickets_query = Ticket.find(query)

    total = await tickets_query.count()
    tickets = await tickets_query.sort(-Ticket.created_at).skip(skip).limit(per_page).to_list() # type: ignore

    # Get project info for each ticket
    project_ids = list(set(t.project_id for t in tickets if t.project_id))
    if project_ids:
        project_object_ids = [PydanticObjectId(pid) for pid in project_ids]
        projects = await Project.find({"_id": {"$in": project_object_ids}}).to_list()
    else:
        projects = []
    projects_map = {str(p.id): p for p in projects}

    # Get all projects for filter dropdown
    all_projects = await Project.find().to_list()

    # Pagination info
    total_pages = (total + per_page - 1) // per_page

    return templates.TemplateResponse(
        request,
        "tickets/list.html",
        {
            "user": user,
            "tickets": tickets,
            "projects_map": projects_map,
            "all_projects": all_projects,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "project_id": project_id,
            "status_filter": status_filter,
            "search": search,
            "statuses": [s.value for s in TicketStatus],
        },
    )


@router.get("/{ticket_id}", response_class=HTMLResponse)
async def view_ticket(request: Request, ticket_id: str, user: CurrentUser):
    """View ticket details."""
    ticket = await Ticket.get(ticket_id)
    if not ticket:
        return RedirectResponse(url="/tickets", status_code=status.HTTP_302_FOUND)

    # Get project and namespace info
    project = await Project.get(ticket.project_id)
    namespace = await Namespace.get(project.namespace_id) if project else None

    # Get acknowledger info
    acknowledger = None
    if ticket.acknowledged_by and ticket.acknowledged_by != "link":
        acknowledger = await User.get(ticket.acknowledged_by)

    return templates.TemplateResponse(
        request,
        "tickets/detail.html",
        {
            "user": user,
            "ticket": ticket,
            "project": project,
            "namespace": namespace,
            "acknowledger": acknowledger,
        },
    )


@router.post("/{ticket_id}/ack")
async def acknowledge_ticket(ticket_id: str, user: CurrentUser):
    """Acknowledge a ticket from WebUI."""
    ticket = await Ticket.get(ticket_id)
    if not ticket:
        return RedirectResponse(url="/tickets", status_code=status.HTTP_302_FOUND)

    if ticket.status == TicketStatus.PENDING or ticket.status == TicketStatus.ESCALATED:
        ticket.status = TicketStatus.ACKNOWLEDGED
        ticket.acknowledged_at = datetime.utcnow()
        ticket.acknowledged_by = str(user.id)
        ticket.updated_at = datetime.utcnow()
        ticket.add_event(
            EventType.ACKNOWLEDGED,
            details=f"由 {user.username} 确认",
        )
        await ticket.save()

        # Send acknowledgement notification
        try:
            await NotificationService.notify_ticket_acknowledged(ticket, acknowledged_by_name=user.username)
        except Exception as e:
            logger.error(f"Failed to send ack notification for ticket {ticket_id}: {e}")

    return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{ticket_id}/resolve")
async def resolve_ticket(ticket_id: str, user: CurrentUser):
    """Resolve a ticket from WebUI."""
    ticket = await Ticket.get(ticket_id)
    if not ticket:
        return RedirectResponse(url="/tickets", status_code=status.HTTP_302_FOUND)

    if ticket.status != TicketStatus.RESOLVED:
        ticket.status = TicketStatus.RESOLVED
        ticket.resolved_at = datetime.utcnow()
        ticket.updated_at = datetime.utcnow()
        ticket.add_event(
            EventType.RESOLVED,
            details=f"由 {user.username} 标记解决",
        )
        await ticket.save()

    return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=status.HTTP_302_FOUND)
