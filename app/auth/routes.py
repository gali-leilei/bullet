"""Authentication routes."""

from datetime import datetime

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth.utils import verify_password
from app.models.user import User
from app.web.templates import templates

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Display login page."""
    # Redirect if already logged in
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"error": None},
    )


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """Process login form."""
    # Find user by username
    user = await User.find_one(User.username == username)

    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Invalid username or password"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if not user.is_active:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Account is disabled"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # Set session
    request.session["user_id"] = str(user.id)

    # Update last login time
    user.last_login_at = datetime.utcnow()
    await user.save()

    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


@router.get("/logout")
async def logout(request: Request):
    """Log out the current user."""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

