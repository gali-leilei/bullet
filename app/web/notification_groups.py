"""Notification group management routes - global resources."""

from datetime import datetime

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import CurrentUser
from app.models.contact import Contact
from app.models.notification_group import (
    REPEAT_INTERVAL_OPTIONS,
    ChannelConfig,
    ChannelType,
    NotificationGroup,
)
from app.web.templates import templates

router = APIRouter(prefix="/notification-groups", tags=["notification_groups"])


@router.get("/", response_class=HTMLResponse)
async def list_groups(request: Request, user: CurrentUser):
    """List all notification groups."""
    groups = await NotificationGroup.find().sort(NotificationGroup.name).to_list()

    # Get all contacts for display
    contacts = await Contact.find().to_list()
    contacts_map = {str(c.id): c for c in contacts}

    return templates.TemplateResponse(
        request,
        "notification_groups/list.html",
        {"user": user, "groups": groups, "contacts_map": contacts_map},
    )


@router.get("/new", response_class=HTMLResponse)
async def new_group_form(request: Request, user: CurrentUser):
    """Display new notification group form."""
    contacts = await Contact.find().sort(Contact.name).to_list()
    channel_types = [t.value for t in ChannelType]

    return templates.TemplateResponse(
        request,
        "notification_groups/form.html",
        {
            "user": user,
            "group": None,
            "contacts": contacts,
            "channel_types": channel_types,
            "repeat_interval_options": REPEAT_INTERVAL_OPTIONS,
            "error": None,
        },
    )


@router.post("/new", response_class=HTMLResponse)
async def create_group(request: Request, user: CurrentUser):
    """Create a new notification group."""
    form_data = await request.form()
    name_raw = form_data.get("name", "")
    name = name_raw.strip() if isinstance(name_raw, str) else ""
    desc_raw = form_data.get("description", "")
    description = desc_raw.strip() if isinstance(desc_raw, str) else ""
    repeat_interval_str = form_data.get("repeat_interval", "")
    repeat_interval = (
        int(repeat_interval_str)
        if isinstance(repeat_interval_str, str) and repeat_interval_str
        else None
    )
    if repeat_interval == 0:
        repeat_interval = None

    # Check if name already exists
    existing = await NotificationGroup.find_one(NotificationGroup.name == name)
    if existing:
        contacts = await Contact.find().sort(Contact.name).to_list()
        channel_types = [t.value for t in ChannelType]
        return templates.TemplateResponse(
            request,
            "notification_groups/form.html",
            {
                "user": user,
                "group": None,
                "contacts": contacts,
                "channel_types": channel_types,
                "repeat_interval_options": REPEAT_INTERVAL_OPTIONS,
                "error": f"Name '{name}' already exists",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Parse channel configs from form
    channel_configs = []
    count_raw = form_data.get("channel_count", 0)
    channel_count = (
        int(count_raw) if isinstance(count_raw, (str, int)) and count_raw else 0
    )

    for i in range(channel_count):
        channel_type = form_data.get(f"channel_{i}_type")
        contact_ids = form_data.getlist(f"channel_{i}_contacts")

        if channel_type and contact_ids:
            channel_configs.append(
                ChannelConfig(
                    type=ChannelType(channel_type),
                    contact_ids=list(contact_ids),
                )
            )

    group = NotificationGroup(
        name=name,
        description=description,
        repeat_interval=repeat_interval,
        channel_configs=channel_configs,
    )
    await group.insert()

    return RedirectResponse(
        url="/notification-groups", status_code=status.HTTP_302_FOUND
    )


@router.get("/{group_id}/edit", response_class=HTMLResponse)
async def edit_group_form(request: Request, group_id: str, user: CurrentUser):
    """Display edit notification group form."""
    group = await NotificationGroup.get(group_id)

    if not group:
        return RedirectResponse(
            url="/notification-groups", status_code=status.HTTP_302_FOUND
        )

    contacts = await Contact.find().sort(Contact.name).to_list()
    channel_types = [t.value for t in ChannelType]

    return templates.TemplateResponse(
        request,
        "notification_groups/form.html",
        {
            "user": user,
            "group": group,
            "contacts": contacts,
            "channel_types": channel_types,
            "repeat_interval_options": REPEAT_INTERVAL_OPTIONS,
            "error": None,
        },
    )


@router.post("/{group_id}/edit", response_class=HTMLResponse)
async def update_group(request: Request, group_id: str, user: CurrentUser):
    """Update a notification group."""
    group = await NotificationGroup.get(group_id)

    if not group:
        return RedirectResponse(
            url="/notification-groups", status_code=status.HTTP_302_FOUND
        )

    form_data = await request.form()
    name_raw = form_data.get("name", "")
    name = name_raw.strip() if isinstance(name_raw, str) else ""
    desc_raw = form_data.get("description", "")
    description = desc_raw.strip() if isinstance(desc_raw, str) else ""
    repeat_interval_str = form_data.get("repeat_interval", "")
    repeat_interval = (
        int(repeat_interval_str)
        if isinstance(repeat_interval_str, str) and repeat_interval_str
        else None
    )
    if repeat_interval == 0:
        repeat_interval = None

    # Check if name is taken by another group
    existing = await NotificationGroup.find_one(NotificationGroup.name == name)
    if existing and str(existing.id) != group_id:
        contacts = await Contact.find().sort(Contact.name).to_list()
        channel_types = [t.value for t in ChannelType]
        return templates.TemplateResponse(
            request,
            "notification_groups/form.html",
            {
                "user": user,
                "group": group,
                "contacts": contacts,
                "channel_types": channel_types,
                "repeat_interval_options": REPEAT_INTERVAL_OPTIONS,
                "error": f"Name '{name}' already exists",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Parse channel configs from form
    channel_configs = []
    count_raw = form_data.get("channel_count", 0)
    channel_count = (
        int(count_raw) if isinstance(count_raw, (str, int)) and count_raw else 0
    )

    for i in range(channel_count):
        channel_type = form_data.get(f"channel_{i}_type")
        contact_ids = form_data.getlist(f"channel_{i}_contacts")

        if channel_type and contact_ids:
            channel_configs.append(
                ChannelConfig(
                    type=ChannelType(channel_type),
                    contact_ids=list(contact_ids),
                )
            )

    group.name = name
    group.description = description
    group.repeat_interval = repeat_interval
    group.channel_configs = channel_configs
    group.updated_at = datetime.utcnow()

    await group.save()

    return RedirectResponse(
        url="/notification-groups", status_code=status.HTTP_302_FOUND
    )


@router.post("/{group_id}/delete")
async def delete_group(group_id: str, user: CurrentUser):
    """Delete a notification group."""
    group = await NotificationGroup.get(group_id)
    if group:
        await group.delete()

    return RedirectResponse(
        url="/notification-groups", status_code=status.HTTP_302_FOUND
    )
