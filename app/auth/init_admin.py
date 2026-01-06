"""Initialize admin user on first startup."""

import logging

from app.auth.utils import hash_password
from app.config import get_settings
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)


async def ensure_admin_exists() -> None:
    """Create initial admin user if no users exist.

    Uses ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_EMAIL from environment.
    """
    settings = get_settings()

    # Check if any users exist
    user_count = await User.count()
    if user_count > 0:
        logger.info(f"Found {user_count} existing user(s), skipping admin initialization")
        return

    # Require admin password to be set
    if not settings.admin_password:
        logger.warning(
            "No users exist and ADMIN_PASSWORD is not set. "
            "Set ADMIN_PASSWORD environment variable to create initial admin."
        )
        return

    # Create admin user
    admin = User(
        username=settings.admin_username,
        password_hash=hash_password(settings.admin_password),
        email=settings.admin_email,
        role=UserRole.ADMIN,
        is_active=True,
    )
    await admin.insert()

    logger.info(f"Created initial admin user: {settings.admin_username}")

