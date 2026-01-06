"""User management routes."""

from datetime import datetime

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth.utils import hash_password
from app.deps import AdminUser
from app.models.user import User, UserRole
from app.web.templates import templates

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/", response_class=HTMLResponse)
async def list_users(request: Request, admin: AdminUser):
    """List all users."""
    users = await User.find().sort(User.created_at).to_list()
    return templates.TemplateResponse(
        request,
        "users/list.html",
        {"user": admin, "users": users},
    )


@router.get("/new", response_class=HTMLResponse)
async def new_user_form(request: Request, admin: AdminUser):
    """Display new user form."""
    return templates.TemplateResponse(
        request,
        "users/form.html",
        {"user": admin, "target_user": None, "roles": UserRole, "error": None},
    )


@router.post("/new", response_class=HTMLResponse)
async def create_user(
    request: Request,
    admin: AdminUser,
    username: str = Form(...),
    password: str = Form(...),
    email: str = Form(""),
    role: str = Form("user"),
):
    """Create a new user."""
    # Check if username already exists
    existing = await User.find_one(User.username == username)
    if existing:
        return templates.TemplateResponse(
            request,
            "users/form.html",
            {
                "user": admin,
                "target_user": None,
                "roles": UserRole,
                "error": "Username already exists",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    new_user = User(
        username=username,
        password_hash=hash_password(password),
        email=email if email else None,
        role=UserRole(role),
        is_active=True,
    )
    await new_user.insert()

    return RedirectResponse(url="/users", status_code=status.HTTP_302_FOUND)


@router.get("/{user_id}", response_class=HTMLResponse)
async def edit_user_form(request: Request, user_id: str, admin: AdminUser):
    """Display edit user form."""
    target_user = await User.get(user_id)
    if not target_user:
        return RedirectResponse(url="/users", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        request,
        "users/form.html",
        {"user": admin, "target_user": target_user, "roles": UserRole, "error": None},
    )


@router.post("/{user_id}", response_class=HTMLResponse)
async def update_user(
    request: Request,
    user_id: str,
    admin: AdminUser,
    username: str = Form(...),
    password: str = Form(""),
    email: str = Form(""),
    role: str = Form("user"),
    is_active: bool = Form(False),
):
    """Update a user."""
    target_user = await User.get(user_id)
    if not target_user:
        return RedirectResponse(url="/users", status_code=status.HTTP_302_FOUND)

    # Check if username is taken by another user
    existing = await User.find_one(User.username == username)
    if existing and str(existing.id) != user_id:
        return templates.TemplateResponse(
            request,
            "users/form.html",
            {
                "user": admin,
                "target_user": target_user,
                "roles": UserRole,
                "error": "Username already taken",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    target_user.username = username
    target_user.email = email if email else None
    target_user.role = UserRole(role)
    target_user.is_active = is_active
    target_user.updated_at = datetime.utcnow()

    if password:
        target_user.password_hash = hash_password(password)

    await target_user.save()

    return RedirectResponse(url="/users", status_code=status.HTTP_302_FOUND)


@router.post("/{user_id}/delete")
async def delete_user(user_id: str, admin: AdminUser):
    """Delete a user."""
    target_user = await User.get(user_id)
    if target_user and str(target_user.id) != str(admin.id):
        await target_user.delete()

    return RedirectResponse(url="/users", status_code=status.HTTP_302_FOUND)

