"""Bullet - FastAPI application for webhook relay with WebUI management."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api.webhook import get_sources
from app.config import get_settings
from app.database import close_db, init_db

# from app.sources.base import BaseSource
# from app.sources.grafana import GrafanaSource

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Source parsers registry
# sources: dict[str, BaseSource] = {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup/shutdown."""
    settings = get_settings()

    # Configure logging level
    logging.getLogger().setLevel(settings.log_level.upper())

    # Initialize MongoDB
    await init_db()

    # Create initial admin user if needed
    from app.auth.init_admin import ensure_admin_exists

    await ensure_admin_exists()

    # Ensure built-in notification templates exist
    from app.services.template import TemplateService

    await TemplateService.ensure_builtin_templates()

    # Register source parsers
    # from app.sources.aliyun_pai import AliyunSource

    # sources["grafana"] = GrafanaSource()
    # sources["aliyun"] = AliyunSource()
    sources = get_sources()
    logger.info(f"Registered {len(sources)} source parser(s): {list(sources.keys())}")

    # Start escalation scheduler
    from app.services.escalation import start_scheduler, stop_scheduler

    start_scheduler()

    logger.info("Bullet started")

    yield

    # Cleanup on shutdown
    stop_scheduler()
    await close_db()
    sources.clear()
    logger.info("Bullet stopped")


# Create FastAPI app
app = FastAPI(
    title="Bullet",
    description="Webhook relay service for alerts with WebUI management",
    version="0.4.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Add session middleware
settings = get_settings()
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie=settings.session_cookie_name,
    max_age=settings.session_max_age,
    same_site="lax",
    https_only=False,  # Set to True in production with HTTPS
)

# Mount static files
import os  # noqa: E402

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Include routers
from app.api.ack import router as ack_router  # noqa: E402
from app.api.webhook import router as webhook_router  # noqa: E402
from app.auth.routes import router as auth_router  # noqa: E402
from app.web.contacts import router as contacts_router  # noqa: E402
from app.web.dashboard import router as dashboard_router  # noqa: E402
from app.web.namespaces import router as namespaces_router  # noqa: E402
from app.web.notification_groups import (
    router as notification_groups_router,  # noqa: E402
)
from app.web.notification_templates import (
    router as notification_templates_router,  # noqa: E402
)
from app.web.tickets import router as tickets_router  # noqa: E402
from app.web.users import router as users_router  # noqa: E402

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(users_router)
app.include_router(contacts_router)
app.include_router(namespaces_router)
app.include_router(notification_groups_router)
app.include_router(notification_templates_router)
app.include_router(tickets_router)
app.include_router(webhook_router)
app.include_router(ack_router)


# Exception handler for 401/403 errors - redirect to login for web routes
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions, redirecting to login for auth errors on web routes."""
    # API routes should return JSON
    path = request.url.path
    api_paths = ["/api", "/webhook", "/ack", "/health"]
    is_api_request = any(path.startswith(p) for p in api_paths)

    # Check Accept header for API clients
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        is_api_request = True

    # For web routes with auth errors, redirect to login
    if not is_api_request and exc.status_code in (401, 403):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    # Otherwise return JSON error
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


# Authentication middleware for web routes
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Redirect unauthenticated users to login for web routes."""
    # Skip auth check for these paths
    public_paths = [
        "/login",
        "/logout",
        "/health",
        "/api",
        "/static",
        "/webhook",
        "/ack",
    ]

    path = request.url.path
    if any(path.startswith(p) for p in public_paths):
        return await call_next(request)

    # Check if user is authenticated
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    except (AssertionError, AttributeError):
        # Session middleware not yet initialized, let exception handler deal with it
        pass

    return await call_next(request)


# Health check endpoint
@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


# API routes for sources
@app.get("/api/sources")
async def list_sources() -> dict[str, list[str]]:
    """List registered alert sources."""
    sources = get_sources()
    return {"sources": list(sources.keys())}


def run() -> None:
    """Run the application using uvicorn."""
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    run()
