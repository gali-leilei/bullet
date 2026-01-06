"""Dashboard routes."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.deps import CurrentUser
from app.models import Contact, Namespace, NotificationGroup, Project, Ticket, TicketStatus, User
from app.web.templates import templates

router = APIRouter(tags=["dashboard"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, user: CurrentUser):
    """Display dashboard with system overview."""
    # Gather statistics
    stats = {
        "namespaces": await Namespace.count(),
        "projects": await Project.count(),
        "contacts": await Contact.count(),
        "pending_tickets": await Ticket.find(Ticket.status == TicketStatus.PENDING).count(),
        "users": await User.count(),
        "notification_groups": await NotificationGroup.count(),
    }

    # Get recent tickets
    recent_tickets = await Ticket.find().sort(-Ticket.created_at).limit(5).to_list()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "stats": stats,
            "recent_tickets": recent_tickets,
        },
    )

