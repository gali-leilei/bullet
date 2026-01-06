"""Acknowledgement API for tickets."""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.models.ticket import EventType, Ticket, TicketStatus
from app.services.notification import NotificationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ack", tags=["acknowledgement"])


@router.get("/{ticket_id}")
async def acknowledge_ticket_via_link(
    ticket_id: str,
    token: str = Query(..., description="Acknowledgement token"),
    format: str = Query(default="redirect", description="Response format: redirect, json, html"),
):
    """Acknowledge a ticket via callback link.

    This endpoint is included in notification messages for one-click acknowledgement.
    """
    ticket = await Ticket.get(ticket_id)

    if not ticket:
        if format == "json":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
        return HTMLResponse(
            content="<html><body><h1>Ticket not found</h1></body></html>",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # Verify token
    if ticket.ack_token != token:
        if format == "json":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token")
        return HTMLResponse(
            content="<html><body><h1>Invalid token</h1></body></html>",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # Check if already acknowledged
    if ticket.status == TicketStatus.ACKNOWLEDGED:
        if format == "json":
            return JSONResponse(content={"status": "already_acknowledged", "ticket_id": str(ticket.id)})
        if format == "html":
            return HTMLResponse(content="<html><body><h1>Already acknowledged</h1></body></html>")
        return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=status.HTTP_302_FOUND)

    if ticket.status == TicketStatus.RESOLVED:
        if format == "json":
            return JSONResponse(content={"status": "already_resolved", "ticket_id": str(ticket.id)})
        if format == "html":
            return HTMLResponse(content="<html><body><h1>Already resolved</h1></body></html>")
        return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=status.HTTP_302_FOUND)

    # Acknowledge the ticket
    ticket.status = TicketStatus.ACKNOWLEDGED
    ticket.acknowledged_at = datetime.utcnow()
    ticket.acknowledged_by = "link"  # Acknowledged via link, no user ID
    ticket.updated_at = datetime.utcnow()
    ticket.add_event(
        EventType.ACKNOWLEDGED,
        details="通过回调链接确认",
    )
    await ticket.save()

    logger.info(f"Ticket {ticket_id} acknowledged via link")

    # Send acknowledgement notification (async, don't wait for result)
    try:
        await NotificationService.notify_ticket_acknowledged(ticket, acknowledged_by_name="链接确认")
    except Exception as e:
        logger.error(f"Failed to send ack notification for ticket {ticket_id}: {e}")

    if format == "json":
        return JSONResponse(content={"status": "acknowledged", "ticket_id": str(ticket.id)})

    if format == "html":
        return HTMLResponse(
            content=f"""
            <html>
            <head><title>Acknowledged</title></head>
            <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                <h1 style="color: green;">✓ Ticket Acknowledged</h1>
                <p>Ticket ID: {ticket_id}</p>
                <p>Time: {ticket.acknowledged_at.strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            </body>
            </html>
            """
        )

    return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=status.HTTP_302_FOUND)
