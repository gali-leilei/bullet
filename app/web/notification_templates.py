"""Notification template management routes."""

from datetime import datetime

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import CurrentUser
from app.models.notification_template import NotificationTemplate
from app.web.templates import templates

router = APIRouter(prefix="/notification-templates", tags=["notification_templates"])


@router.get("/", response_class=HTMLResponse)
async def list_templates(request: Request, user: CurrentUser):
    """List all notification templates."""
    template_list = (
        await NotificationTemplate.find().sort(NotificationTemplate.name).to_list()
    )

    return templates.TemplateResponse(
        request,
        "notification_templates/list.html",
        {"user": user, "templates": template_list},
    )


@router.get("/new", response_class=HTMLResponse)
async def new_template_form(request: Request, user: CurrentUser):
    """Display new notification template form."""
    return templates.TemplateResponse(
        request,
        "notification_templates/form.html",
        {
            "user": user,
            "template": None,
            "error": None,
        },
    )


@router.post("/new", response_class=HTMLResponse)
async def create_template(request: Request, user: CurrentUser):
    """Create a new notification template."""
    form_data = await request.form()
    name_raw = form_data.get("name", "")
    name = name_raw.strip() if isinstance(name_raw, str) else ""
    desc_raw = form_data.get("description", "")
    description = desc_raw.strip() if isinstance(desc_raw, str) else ""
    feishu_raw = form_data.get("feishu_card", "")
    feishu_card = feishu_raw.strip() if isinstance(feishu_raw, str) else ""
    subject_raw = form_data.get("email_subject", "")
    email_subject = subject_raw.strip() if isinstance(subject_raw, str) else ""
    body_raw = form_data.get("email_body", "")
    email_body = body_raw.strip() if isinstance(body_raw, str) else ""
    sms_raw = form_data.get("sms_message", "")
    sms_message = sms_raw.strip() if isinstance(sms_raw, str) else ""

    # Check if name already exists
    existing = await NotificationTemplate.find_one(NotificationTemplate.name == name)
    if existing:
        return templates.TemplateResponse(
            request,
            "notification_templates/form.html",
            {
                "user": user,
                "template": None,
                "error": f"Name '{name}' already exists",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    template = NotificationTemplate(
        name=name,
        description=description,
        is_builtin=False,
        feishu_card=feishu_card,
        email_subject=email_subject,
        email_body=email_body,
        sms_message=sms_message,
    )
    await template.insert()

    return RedirectResponse(
        url="/notification-templates", status_code=status.HTTP_302_FOUND
    )


@router.get("/{template_id}/edit", response_class=HTMLResponse)
async def edit_template_form(request: Request, template_id: str, user: CurrentUser):
    """Display edit notification template form."""
    template = await NotificationTemplate.get(template_id)

    if not template:
        return RedirectResponse(
            url="/notification-templates", status_code=status.HTTP_302_FOUND
        )

    return templates.TemplateResponse(
        request,
        "notification_templates/form.html",
        {
            "user": user,
            "template": template,
            "error": None,
        },
    )


@router.post("/{template_id}/edit", response_class=HTMLResponse)
async def update_template(request: Request, template_id: str, user: CurrentUser):
    """Update a notification template."""
    template = await NotificationTemplate.get(template_id)

    if not template:
        return RedirectResponse(
            url="/notification-templates", status_code=status.HTTP_302_FOUND
        )

    form_data = await request.form()
    name_raw = form_data.get("name", "")
    name = name_raw.strip() if isinstance(name_raw, str) else ""
    desc_raw = form_data.get("description", "")
    description = desc_raw.strip() if isinstance(desc_raw, str) else ""
    feishu_raw = form_data.get("feishu_card", "")
    feishu_card = feishu_raw.strip() if isinstance(feishu_raw, str) else ""
    subject_raw = form_data.get("email_subject", "")
    email_subject = subject_raw.strip() if isinstance(subject_raw, str) else ""
    body_raw = form_data.get("email_body", "")
    email_body = body_raw.strip() if isinstance(body_raw, str) else ""
    sms_raw = form_data.get("sms_message", "")
    sms_message = sms_raw.strip() if isinstance(sms_raw, str) else ""

    # Check if name is taken by another template
    existing = await NotificationTemplate.find_one(NotificationTemplate.name == name)
    if existing and str(existing.id) != template_id:
        return templates.TemplateResponse(
            request,
            "notification_templates/form.html",
            {
                "user": user,
                "template": template,
                "error": f"Name '{name}' already exists",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    template.name = name
    template.description = description
    template.feishu_card = feishu_card
    template.email_subject = email_subject
    template.email_body = email_body
    template.sms_message = sms_message
    template.updated_at = datetime.utcnow()

    await template.save()

    return RedirectResponse(
        url="/notification-templates", status_code=status.HTTP_302_FOUND
    )


@router.post("/{template_id}/delete")
async def delete_template(template_id: str, user: CurrentUser):
    """Delete a notification template."""
    template = await NotificationTemplate.get(template_id)
    if template:
        # Cannot delete built-in templates
        if template.is_builtin:
            return RedirectResponse(
                url="/notification-templates", status_code=status.HTTP_302_FOUND
            )
        await template.delete()

    return RedirectResponse(
        url="/notification-templates", status_code=status.HTTP_302_FOUND
    )
