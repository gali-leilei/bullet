"""Namespace and Project management routes."""

import logging
import re
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import get_settings
from app.deps import CurrentUser
from app.models.contact import Contact
from app.models.namespace import Namespace
from app.models.notification_group import NotificationGroup
from app.models.notification_template import NotificationTemplate
from app.models.project import SILENCE_DURATION_OPTIONS, EscalationConfig, Project
from app.models.ticket import Ticket, TicketStatus
from app.services.notification import NotificationService
from app.services.template import TemplateService
from app.web.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/namespaces", tags=["namespaces"])

# Severity options for test message
SEVERITY_OPTIONS = [
    ("critical", "Critical - 严重"),
    ("error", "Error - 错误"),
    ("warning", "Warning - 警告"),
    ("info", "Info - 信息"),
    ("notice", "Notice - 通知"),
]


def slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text


# ==================== Namespace Routes ====================


@router.get("/", response_class=HTMLResponse)
async def list_namespaces(request: Request, user: CurrentUser):
    """List all namespaces."""
    namespaces = await Namespace.find().sort(Namespace.name).to_list()

    # Get project counts for each namespace
    namespace_projects = {}
    for ns in namespaces:
        count = await Project.find(Project.namespace_id == str(ns.id)).count()
        namespace_projects[str(ns.id)] = count

    return templates.TemplateResponse(
        request,
        "namespaces/list.html",
        {
            "user": user,
            "namespaces": namespaces,
            "namespace_projects": namespace_projects,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_namespace_form(request: Request, user: CurrentUser):
    """Display new namespace form."""
    return templates.TemplateResponse(
        request,
        "namespaces/form.html",
        {"user": user, "namespace": None, "error": None},
    )


@router.post("/new", response_class=HTMLResponse)
async def create_namespace(request: Request, user: CurrentUser):
    """Create a new namespace."""
    form_data = await request.form()
    name_raw = form_data.get("name", "")
    name = name_raw.strip() if isinstance(name_raw, str) else ""
    slug_raw = form_data.get("slug", "")
    slug = slug_raw.strip() if isinstance(slug_raw, str) else ""
    desc_raw = form_data.get("description", "")
    description = desc_raw.strip() if isinstance(desc_raw, str) else ""

    # Generate slug if not provided
    if not slug:
        slug = slugify(name)

    # Check if slug already exists
    existing = await Namespace.find_one(Namespace.slug == slug)
    if existing:
        return templates.TemplateResponse(
            request,
            "namespaces/form.html",
            {"user": user, "namespace": None, "error": f"Slug '{slug}' already exists"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    namespace = Namespace(
        name=name,
        slug=slug,
        description=description,
    )
    await namespace.insert()

    return RedirectResponse(url="/namespaces", status_code=status.HTTP_302_FOUND)


@router.get("/{namespace_id}", response_class=HTMLResponse)
async def view_namespace(request: Request, namespace_id: str, user: CurrentUser):
    """View namespace details and projects."""
    namespace = await Namespace.get(namespace_id)
    if not namespace:
        return RedirectResponse(url="/namespaces", status_code=status.HTTP_302_FOUND)

    projects = (
        await Project.find(Project.namespace_id == str(namespace.id))
        .sort(Project.name)
        .to_list()
    )

    # Get notification group count for each project (based on bound groups)
    project_group_counts = {}
    for proj in projects:
        project_group_counts[str(proj.id)] = len(proj.notification_group_ids)

    settings = get_settings()

    return templates.TemplateResponse(
        request,
        "namespaces/detail.html",
        {
            "user": user,
            "namespace": namespace,
            "projects": projects,
            "project_group_counts": project_group_counts,
            "base_url": settings.base_url,
        },
    )


@router.get("/{namespace_id}/edit", response_class=HTMLResponse)
async def edit_namespace_form(request: Request, namespace_id: str, user: CurrentUser):
    """Display edit namespace form."""
    namespace = await Namespace.get(namespace_id)
    if not namespace:
        return RedirectResponse(url="/namespaces", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        request,
        "namespaces/form.html",
        {"user": user, "namespace": namespace, "error": None},
    )


@router.post("/{namespace_id}/edit", response_class=HTMLResponse)
async def update_namespace(request: Request, namespace_id: str, user: CurrentUser):
    """Update a namespace."""
    namespace = await Namespace.get(namespace_id)
    if not namespace:
        return RedirectResponse(url="/namespaces", status_code=status.HTTP_302_FOUND)

    form_data = await request.form()
    name_raw = form_data.get("name", "")
    name = name_raw.strip() if isinstance(name_raw, str) else ""
    slug_raw = form_data.get("slug", "")
    slug = slug_raw.strip() if isinstance(slug_raw, str) else ""
    desc_raw = form_data.get("description", "")
    description = desc_raw.strip() if isinstance(desc_raw, str) else ""

    # Check if slug is taken by another namespace
    existing = await Namespace.find_one(Namespace.slug == slug)
    if existing and str(existing.id) != namespace_id:
        return templates.TemplateResponse(
            request,
            "namespaces/form.html",
            {
                "user": user,
                "namespace": namespace,
                "error": f"Slug '{slug}' already exists",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    namespace.name = name
    namespace.slug = slug
    namespace.description = description
    namespace.updated_at = datetime.utcnow()

    await namespace.save()

    return RedirectResponse(
        url=f"/namespaces/{namespace_id}", status_code=status.HTTP_302_FOUND
    )


@router.post("/{namespace_id}/delete")
async def delete_namespace(namespace_id: str, user: CurrentUser):
    """Delete a namespace and all its projects."""
    namespace = await Namespace.get(namespace_id)
    if namespace:
        # Delete all projects in this namespace (notification groups are global, don't delete)
        await Project.find(Project.namespace_id == str(namespace.id)).delete()
        await namespace.delete()

    return RedirectResponse(url="/namespaces", status_code=status.HTTP_302_FOUND)


# ==================== Project Routes ====================


@router.get("/{namespace_id}/projects/new", response_class=HTMLResponse)
async def new_project_form(request: Request, namespace_id: str, user: CurrentUser):
    """Display new project form."""
    namespace = await Namespace.get(namespace_id)
    if not namespace:
        return RedirectResponse(url="/namespaces", status_code=status.HTTP_302_FOUND)

    # Get all notification groups for binding
    all_groups = await NotificationGroup.find().sort(NotificationGroup.name).to_list()

    # Get all notification templates
    all_templates = (
        await NotificationTemplate.find().sort(NotificationTemplate.name).to_list()
    )

    return templates.TemplateResponse(
        request,
        "projects/form.html",
        {
            "user": user,
            "namespace": namespace,
            "project": None,
            "all_groups": all_groups,
            "all_templates": all_templates,
            "error": None,
        },
    )


@router.post("/{namespace_id}/projects/new", response_class=HTMLResponse)
async def create_project(request: Request, namespace_id: str, user: CurrentUser):
    """Create a new project."""
    namespace = await Namespace.get(namespace_id)
    if not namespace:
        return RedirectResponse(url="/namespaces", status_code=status.HTTP_302_FOUND)

    form_data = await request.form()
    name_raw = form_data.get("name", "")
    name = name_raw.strip() if isinstance(name_raw, str) else ""
    desc_raw = form_data.get("description", "")
    description = desc_raw.strip() if isinstance(desc_raw, str) else ""
    escalation_enabled = form_data.get("escalation_enabled") == "on"
    timeout_raw = form_data.get("escalation_timeout", 15)
    escalation_timeout = (
        int(timeout_raw) if isinstance(timeout_raw, (str, int)) and timeout_raw else 15
    )
    notification_group_ids = form_data.getlist("notification_group_ids")
    template_id_raw = form_data.get("notification_template_id", "")
    notification_template_id = (
        template_id_raw.strip() if isinstance(template_id_raw, str) else ""
    )
    notify_on_ack = form_data.get("notify_on_ack") == "on"

    project = Project(
        namespace_id=str(namespace.id),
        name=name,
        description=description,
        notification_group_ids=list(notification_group_ids),
        notification_template_id=notification_template_id
        if notification_template_id
        else None,
        notify_on_ack=notify_on_ack,
        escalation_config=EscalationConfig(
            enabled=escalation_enabled,
            timeout_minutes=escalation_timeout,
        ),
    )
    await project.insert()

    return RedirectResponse(
        url=f"/namespaces/{namespace_id}", status_code=status.HTTP_302_FOUND
    )


@router.get("/{namespace_id}/projects/{project_id}", response_class=HTMLResponse)
async def view_project(
    request: Request, namespace_id: str, project_id: str, user: CurrentUser
):
    """View project details and bound notification groups."""
    namespace = await Namespace.get(namespace_id)
    project = await Project.get(project_id)

    if not namespace or not project:
        return RedirectResponse(url="/namespaces", status_code=status.HTTP_302_FOUND)

    # Get bound notification groups in order
    bound_groups = []
    for group_id in project.notification_group_ids:
        group = await NotificationGroup.get(group_id)
        if group:
            bound_groups.append(group)

    # Get all contacts for reference
    contacts = await Contact.find().to_list()
    contacts_map = {str(c.id): c for c in contacts}

    settings = get_settings()

    return templates.TemplateResponse(
        request,
        "projects/detail.html",
        {
            "user": user,
            "namespace": namespace,
            "project": project,
            "bound_groups": bound_groups,
            "contacts_map": contacts_map,
            "base_url": settings.base_url,
            "silence_options": SILENCE_DURATION_OPTIONS,
            "severity_options": SEVERITY_OPTIONS,
            "test_result": None,
        },
    )


@router.get("/{namespace_id}/projects/{project_id}/edit", response_class=HTMLResponse)
async def edit_project_form(
    request: Request, namespace_id: str, project_id: str, user: CurrentUser
):
    """Display edit project form."""
    namespace = await Namespace.get(namespace_id)
    project = await Project.get(project_id)

    if not namespace or not project:
        return RedirectResponse(url="/namespaces", status_code=status.HTTP_302_FOUND)

    # Get all notification groups for binding
    all_groups = await NotificationGroup.find().sort(NotificationGroup.name).to_list()

    # Get all notification templates
    all_templates = (
        await NotificationTemplate.find().sort(NotificationTemplate.name).to_list()
    )

    return templates.TemplateResponse(
        request,
        "projects/form.html",
        {
            "user": user,
            "namespace": namespace,
            "project": project,
            "all_groups": all_groups,
            "all_templates": all_templates,
            "error": None,
        },
    )


@router.post("/{namespace_id}/projects/{project_id}/edit", response_class=HTMLResponse)
async def update_project(
    request: Request, namespace_id: str, project_id: str, user: CurrentUser
):
    """Update a project."""
    namespace = await Namespace.get(namespace_id)
    project = await Project.get(project_id)

    if not namespace or not project:
        return RedirectResponse(url="/namespaces", status_code=status.HTTP_302_FOUND)

    form_data = await request.form()
    name_raw = form_data.get("name", "")
    name = name_raw.strip() if isinstance(name_raw, str) else ""
    desc_raw = form_data.get("description", "")
    description = desc_raw.strip() if isinstance(desc_raw, str) else ""
    escalation_enabled = form_data.get("escalation_enabled") == "on"
    timeout_raw = form_data.get("escalation_timeout", 15)
    escalation_timeout = (
        int(timeout_raw) if isinstance(timeout_raw, (str, int)) and timeout_raw else 15
    )
    notification_group_ids = form_data.getlist("notification_group_ids")
    template_id_raw = form_data.get("notification_template_id", "")
    notification_template_id = (
        template_id_raw.strip() if isinstance(template_id_raw, str) else ""
    )
    is_active = form_data.get("is_active") == "on"
    notify_on_ack = form_data.get("notify_on_ack") == "on"

    project.name = name
    project.description = description
    project.notification_group_ids = list(notification_group_ids)
    project.notification_template_id = (
        notification_template_id if notification_template_id else None
    )
    project.is_active = is_active
    project.notify_on_ack = notify_on_ack
    project.escalation_config = EscalationConfig(
        enabled=escalation_enabled,
        timeout_minutes=escalation_timeout,
    )
    project.updated_at = datetime.utcnow()

    await project.save()

    return RedirectResponse(
        url=f"/namespaces/{namespace_id}/projects/{project_id}",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/{namespace_id}/projects/{project_id}/delete")
async def delete_project(namespace_id: str, project_id: str, user: CurrentUser):
    """Delete a project (notification groups are global, not deleted)."""
    project = await Project.get(project_id)
    if project:
        await project.delete()

    return RedirectResponse(
        url=f"/namespaces/{namespace_id}", status_code=status.HTTP_302_FOUND
    )


@router.post("/{namespace_id}/projects/{project_id}/silence")
async def silence_project(
    request: Request, namespace_id: str, project_id: str, user: CurrentUser
):
    """Silence a project for a specified duration."""
    project = await Project.get(project_id)
    if not project:
        return RedirectResponse(
            url=f"/namespaces/{namespace_id}", status_code=status.HTTP_302_FOUND
        )

    form_data = await request.form()
    duration_raw = form_data.get("duration", 30)
    duration_minutes = (
        int(duration_raw)
        if isinstance(duration_raw, (str, int)) and duration_raw
        else 30
    )

    project.silenced_until = datetime.utcnow() + timedelta(minutes=duration_minutes)
    project.updated_at = datetime.utcnow()
    await project.save()

    return RedirectResponse(
        url=f"/namespaces/{namespace_id}/projects/{project_id}",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/{namespace_id}/projects/{project_id}/unsilence")
async def unsilence_project(namespace_id: str, project_id: str, user: CurrentUser):
    """Remove silence from a project."""
    project = await Project.get(project_id)
    if not project:
        return RedirectResponse(
            url=f"/namespaces/{namespace_id}", status_code=status.HTTP_302_FOUND
        )

    project.silenced_until = None
    project.updated_at = datetime.utcnow()
    await project.save()

    return RedirectResponse(
        url=f"/namespaces/{namespace_id}/projects/{project_id}",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/{namespace_id}/projects/{project_id}/test", response_class=HTMLResponse)
async def send_test_message(
    request: Request, namespace_id: str, project_id: str, user: CurrentUser
):
    """Send a test notification to the first notification group."""
    namespace = await Namespace.get(namespace_id)
    project = await Project.get(project_id)

    if not namespace or not project:
        return RedirectResponse(url="/namespaces", status_code=status.HTTP_302_FOUND)

    form_data = await request.form()
    title_raw = form_data.get("title", "")
    title = (title_raw.strip() if isinstance(title_raw, str) else "") or "测试告警"
    desc_raw = form_data.get("description", "")
    description = (
        desc_raw.strip() if isinstance(desc_raw, str) else ""
    ) or "这是一条测试消息，用于验证通知配置是否正确。"
    severity_raw = form_data.get("severity", "warning")
    severity = severity_raw if isinstance(severity_raw, str) else "warning"

    # Check if project has notification groups
    if not project.notification_group_ids:
        return await _render_project_detail_with_test_result(
            request,
            namespace,
            project,
            user,
            test_result={"success": False, "message": "项目未配置通知组"},
        )

    # Get the first notification group
    first_group_id = project.notification_group_ids[0]
    first_group = await NotificationGroup.get(first_group_id)

    if not first_group:
        return await _render_project_detail_with_test_result(
            request,
            namespace,
            project,
            user,
            test_result={"success": False, "message": "第一级通知组不存在"},
        )

    # Create a temporary ticket object (not saved to DB)
    test_ticket = Ticket(
        project_id=str(project.id),
        source="test",
        status=TicketStatus.PENDING,
        payload={"test": True},
        title=title,
        description=description,
        severity=severity,
        labels={"env": "test", "type": "test_message"},
        ack_token=secrets.token_urlsafe(32),
    )

    # Get template for project
    template = await TemplateService.get_template_for_project(project)

    # Send notification to the first group
    try:
        results = await NotificationService.send_to_group(
            test_ticket,
            first_group,
            template=template,
            project=project,
            is_escalated=False,
            is_repeated=False,
        )

        # Summarize results
        success_count = sum(1 for v in results.values() if v)
        fail_count = sum(1 for v in results.values() if not v)

        if not results:
            test_result = {"success": False, "message": "通知组没有配置渠道或联系人"}
        elif fail_count == 0:
            test_result = {
                "success": True,
                "message": f"测试消息发送成功！({success_count} 个渠道)",
                "details": results,
            }
        elif success_count == 0:
            test_result = {
                "success": False,
                "message": f"测试消息发送失败 ({fail_count} 个渠道)",
                "details": results,
            }
        else:
            test_result = {
                "success": True,
                "message": f"测试消息部分成功 ({success_count} 成功, {fail_count} 失败)",
                "details": results,
            }

    except Exception as e:
        logger.exception(f"Error sending test message: {e}")
        test_result = {"success": False, "message": f"发送异常: {str(e)}"}

    return await _render_project_detail_with_test_result(
        request, namespace, project, user, test_result=test_result
    )


async def _render_project_detail_with_test_result(
    request: Request,
    namespace: Namespace,
    project: Project,
    user,
    test_result: dict,
):
    """Render project detail page with test result."""
    # Get bound notification groups in order
    bound_groups = []
    for group_id in project.notification_group_ids:
        group = await NotificationGroup.get(group_id)
        if group:
            bound_groups.append(group)

    # Get all contacts for reference
    contacts = await Contact.find().to_list()
    contacts_map = {str(c.id): c for c in contacts}

    settings = get_settings()

    return templates.TemplateResponse(
        request,
        "projects/detail.html",
        {
            "user": user,
            "namespace": namespace,
            "project": project,
            "bound_groups": bound_groups,
            "contacts_map": contacts_map,
            "base_url": settings.base_url,
            "silence_options": SILENCE_DURATION_OPTIONS,
            "severity_options": SEVERITY_OPTIONS,
            "test_result": test_result,
        },
    )
