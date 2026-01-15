"""Contact management routes."""

from datetime import datetime

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import AdminUser, CurrentUser
from app.models.contact import Contact
from app.models.user import User
from app.web.templates import templates

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
        "slack_bot_token": contact.slack_bot_token,
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


@router.post("/new", response_class=HTMLResponse)
async def create_contact(
    name: str = Form(...),
    phones: str = Form(""),
    emails: str = Form(""),
    feishu_webhook_url: str = Form(""),
    slack_webhook_url: str = Form(""),
    slack_bot_token: str = Form(""),
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
        slack_bot_token=slack_bot_token,
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
    slack_bot_token: str = Form(""),
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
    contact.slack_bot_token = slack_bot_token
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

