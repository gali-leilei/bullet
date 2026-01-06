"""MongoDB connection and Beanie ODM initialization."""

import logging

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import get_settings

logger = logging.getLogger(__name__)

# Global client instance
_client: AsyncIOMotorClient | None = None


async def init_db() -> None:
    """Initialize MongoDB connection and Beanie ODM."""
    global _client

    settings = get_settings()

    logger.info(f"Connecting to MongoDB: {settings.mongodb_uri}")
    _client = AsyncIOMotorClient(settings.mongodb_uri)

    # Import models here to avoid circular imports
    from app.models.contact import Contact
    from app.models.namespace import Namespace
    from app.models.notification_group import NotificationGroup
    from app.models.notification_template import NotificationTemplate
    from app.models.project import Project
    from app.models.ticket import Ticket
    from app.models.user import User

    await init_beanie(
        database=_client[settings.mongodb_database],
        document_models=[
            User,
            Contact,
            Namespace,
            Project,
            NotificationGroup,
            NotificationTemplate,
            Ticket,
        ],
    )

    logger.info(f"Connected to MongoDB database: {settings.mongodb_database}")


async def close_db() -> None:
    """Close MongoDB connection."""
    global _client

    if _client:
        _client.close()
        _client = None
        logger.info("MongoDB connection closed")


def get_client() -> AsyncIOMotorClient:
    """Get the MongoDB client instance."""
    if _client is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _client

