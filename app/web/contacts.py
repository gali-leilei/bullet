"""Contact management routes."""

import logging
from datetime import datetime

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import get_settings
from app.deps import AdminUser, CurrentUser
from app.models.contact import Contact
from app.models.user import User
from app.web.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contacts", tags=["contacts"])


def mask_phone(phone: str) -> str:
    """Mask phone number, showing only first 3 and last 4 digits."""
    if len(phone) <= 7:
        return phone[:1] + "*" * (len(phone) - 2) + phone[-1:] if len(phone) > 2 else phone
    return phone[:3] + "*" * (len(phone) - 7) + phone[-4:]


def mask_email(email: str) -> str:
    """Mask email, hiding characters before @."""
    if "@" not in email:
        return email
    local, domain = email.rsplit("@", 1)
    if len(local) <= 2:
        masked_local = "*" * len(local)
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked_local}@{domain}"


def mask_contact_for_display(contact: Contact, user: User) -> dict:
    """Create a display dict with masked data for non-admin users."""
    data = {
        "id": contact.id,
        "name": contact.name,
        "feishu_webhook_url": contact.feishu_webhook_url,
        "slack_webhook_url": contact.slack_webhook_url,
        "slack_channel_id": contact.slack_channel_id,
        "note": contact.note,
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
    }
    
    if user.is_admin():
        data["phones"] = contact.phones
        data["emails"] = contact.emails
    else:
        data["phones"] = [mask_phone(p) for p in contact.phones]
        data["emails"] = [mask_email(e) for e in contact.emails]
    
    return data


@router.get("/", response_class=HTMLResponse)
async def list_contacts(request: Request, user: CurrentUser):
    """List all contacts."""
    contacts = await Contact.find().sort(Contact.name).to_list()
    # Mask sensitive data for non-admin users
    masked_contacts = [mask_contact_for_display(c, user) for c in contacts]
    return templates.TemplateResponse(
        request,
        "contacts/list.html",
        {"user": user, "contacts": masked_contacts},
    )


@router.get("/new", response_class=HTMLResponse)
async def new_contact_form(request: Request, admin: AdminUser):
    """Display new contact form. Admin only."""
    return templates.TemplateResponse(
        request,
        "contacts/form.html",
        {"user": admin, "contact": None, "error": None},
    )


@router.post("/lookup-slack-user")
async def lookup_slack_user(admin: AdminUser, email: str = Form(...)):
    """Look up Slack user ID by email. Admin only."""
    settings = get_settings()
    
    if not settings.slack_bot_token:
        return JSONResponse(
            {"error": "Slack bot token not configured"},
            status_code=400,
        )
    
    from slack_sdk.web.async_client import AsyncWebClient
    from slack_sdk.errors import SlackApiError
    
    try:
        client = AsyncWebClient(token=settings.slack_bot_token)
        response = await client.users_lookupByEmail(email=email)
        
        user_data = response.get("user") or {}
        user_id = user_data.get("id", "")
        user_name = user_data.get("real_name") or user_data.get("name", "")
        
        return JSONResponse({
            "user_id": user_id,
            "user_name": user_name,
        })
    except SlackApiError as e:
        error_msg = e.response.get("error", "Unknown error")
        logger.warning(f"Slack user lookup failed for {email}: {error_msg}")
        return JSONResponse(
            {"error": f"Slack API error: {error_msg}"},
            status_code=400,
        )
    except Exception as e:
        logger.exception(f"Unexpected error during Slack user lookup: {e}")
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


@router.post("/test-email")
async def test_email(admin: AdminUser, email: str = Form(...)):
    """Send a test email. Admin only."""
    settings = get_settings()
    
    if not settings.resend_api_key or not settings.resend_from_email:
        return JSONResponse(
            {"error": "Resend email not configured"},
            status_code=400,
        )
    
    from app.channels.resend_email import ResendEmailChannel
    from app.models.event import Event
    
    try:
        channel = ResendEmailChannel(
            api_key=settings.resend_api_key,
            from_email=settings.resend_from_email,
            to=[email],
            subject_override="HelloWorld",
            body_override="<p>HelloWorld</p>",
        )
        
        event = Event(source="test", type="test", payload={"message": "HelloWorld"})
        success = await channel.send(event)
        
        if success:
            return JSONResponse({"message": f"Test email sent to {email}"})
        else:
            return JSONResponse({"error": "Failed to send email"}, status_code=500)
    except Exception as e:
        logger.exception(f"Failed to send test email: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/test-phone")
async def test_phone(admin: AdminUser, phone: str = Form(...)):
    """Send a test SMS. Admin only."""
    settings = get_settings()
    
    if not settings.twilio_account_sid or not settings.twilio_auth_token or not settings.twilio_from_number:
        return JSONResponse(
            {"error": "Twilio SMS not configured"},
            status_code=400,
        )
    
    from app.channels.twilio_sms import TwilioSMSChannel
    from app.models.event import Event
    
    try:
        channel = TwilioSMSChannel(
            to_numbers=[phone],
            message_override="HelloWorld",
        )
        
        event = Event(source="test", type="test", payload={"message": "HelloWorld"})
        success = await channel.send(event)
        
        if success:
            return JSONResponse({"message": f"Test SMS sent to {phone}"})
        else:
            return JSONResponse({"error": "Failed to send SMS"}, status_code=500)
    except Exception as e:
        logger.exception(f"Failed to send test SMS: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/test-feishu")
async def test_feishu(admin: AdminUser, webhook_url: str = Form(...)):
    """Send a test Feishu message. Admin only."""
    from app.channels.feishu import FeishuChannel
    from app.models.event import Event
    
    try:
        channel = FeishuChannel(webhook_url=webhook_url)
        
        event = Event(source="test", type="test", payload={"message": "HelloWorld"})
        # Override the message format to send plain text
        import httpx
        message = {"msg_type": "text", "content": {"text": "HelloWorld"}}
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(webhook_url, json=message)
            response.raise_for_status()
            result = response.json()
            
            if result.get("code") != 0:
                return JSONResponse({"error": f"Feishu API error: {result}"}, status_code=400)
        
        return JSONResponse({"message": "Test message sent to Feishu"})
    except Exception as e:
        logger.exception(f"Failed to send test Feishu message: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/test-slack-webhook")
async def test_slack_webhook(admin: AdminUser, webhook_url: str = Form(...)):
    """Send a test Slack webhook message. Admin only."""
    import httpx
    
    try:
        message = {"text": "HelloWorld"}
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(webhook_url, json=message)
            response.raise_for_status()
            
            if response.text != "ok":
                return JSONResponse({"error": f"Slack webhook error: {response.text}"}, status_code=400)
        
        return JSONResponse({"message": "Test message sent to Slack webhook"})
    except Exception as e:
        logger.exception(f"Failed to send test Slack webhook message: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/test-slack-channel")
async def test_slack_channel(admin: AdminUser, channel_id: str = Form(...)):
    """Send a test Slack direct message. Admin only."""
    settings = get_settings()
    
    if not settings.slack_bot_token:
        return JSONResponse(
            {"error": "Slack bot token not configured"},
            status_code=400,
        )
    
    from slack_sdk.web.async_client import AsyncWebClient
    from slack_sdk.errors import SlackApiError
    
    try:
        client = AsyncWebClient(token=settings.slack_bot_token)
        response = await client.chat_postMessage(
            channel=channel_id,
            text="HelloWorld",
        )
        
        if response.get("ok"):
            return JSONResponse({"message": f"Test message sent to Slack channel {channel_id}"})
        else:
            return JSONResponse({"error": f"Slack API error: {response.get('error')}"}, status_code=400)
    except SlackApiError as e:
        error_msg = e.response.get("error", "Unknown error")
        logger.warning(f"Slack message failed for {channel_id}: {error_msg}")
        return JSONResponse(
            {"error": f"Slack API error: {error_msg}"},
            status_code=400,
        )
    except Exception as e:
        logger.exception(f"Failed to send test Slack message: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/new", response_class=HTMLResponse)
async def create_contact(
    name: str = Form(...),
    phones: str = Form(""),
    emails: str = Form(""),
    feishu_webhook_url: str = Form(""),
    slack_webhook_url: str = Form(""),
    slack_channel_id: str = Form(""),
    note: str = Form(""),
):
    """Create a new contact. Admin only."""
    # Parse comma-separated phones and emails
    phone_list = [p.strip() for p in phones.split(",") if p.strip()]
    email_list = [e.strip() for e in emails.split(",") if e.strip()]

    contact = Contact(
        name=name,
        phones=phone_list,
        emails=email_list,
        feishu_webhook_url=feishu_webhook_url,
        slack_webhook_url=slack_webhook_url,
        slack_channel_id=slack_channel_id,
        note=note,
    )
    await contact.insert()

    return RedirectResponse(url="/contacts", status_code=status.HTTP_302_FOUND)


@router.get("/{contact_id}", response_class=HTMLResponse)
async def edit_contact_form(request: Request, contact_id: str, admin: AdminUser):
    """Display edit contact form. Admin only."""
    contact = await Contact.get(contact_id)
    if not contact:
        return RedirectResponse(url="/contacts", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        request,
        "contacts/form.html",
        {"user": admin, "contact": contact, "error": None},
    )


@router.post("/{contact_id}", response_class=HTMLResponse)
async def update_contact(
    contact_id: str,
    name: str = Form(...),
    phones: str = Form(""),
    emails: str = Form(""),
    feishu_webhook_url: str = Form(""),
    slack_webhook_url: str = Form(""),
    slack_channel_id: str = Form(""),
    note: str = Form(""),
):
    """Update a contact. Admin only."""
    contact = await Contact.get(contact_id)
    if not contact:
        return RedirectResponse(url="/contacts", status_code=status.HTTP_302_FOUND)

    # Parse comma-separated phones and emails
    phone_list = [p.strip() for p in phones.split(",") if p.strip()]
    email_list = [e.strip() for e in emails.split(",") if e.strip()]

    contact.name = name
    contact.phones = phone_list
    contact.emails = email_list
    contact.feishu_webhook_url = feishu_webhook_url
    contact.slack_webhook_url = slack_webhook_url
    contact.slack_channel_id = slack_channel_id
    contact.note = note
    contact.updated_at = datetime.utcnow()

    await contact.save()

    return RedirectResponse(url="/contacts", status_code=status.HTTP_302_FOUND)


@router.post("/{contact_id}/delete")
async def delete_contact(contact_id: str, admin: AdminUser):
    """Delete a contact. Admin only."""
    contact = await Contact.get(contact_id)
    if contact:
        await contact.delete()

    return RedirectResponse(url="/contacts", status_code=status.HTTP_302_FOUND)

