#!/usr/bin/env python3
"""
Migration:
  1. Rename legacy "slack" channel type to "slack-webhook" in notification_groups
  2. Rename legacy "slack_webhook" field to "slack_webhook_url" in contacts

Usage:
    python app/migration.py [--dry-run]
"""

import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "bullet")


async def migrate(dry_run: bool = False):
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[MONGODB_DATABASE]

    # Migration 1: notification_groups channel type
    print("\n[1] Migrating notification_groups: 'slack' -> 'slack-webhook'")
    ng_collection = db["notification_groups"]
    ng_count = await ng_collection.count_documents({"channel_configs.type": "slack"})
    print(f"    Found {ng_count} document(s)")

    if ng_count > 0:
        if dry_run:
            cursor = ng_collection.find({"channel_configs.type": "slack"}, {"name": 1})
            async for doc in cursor:
                print(f"      Would migrate: {doc.get('name')}")
        else:
            result = await ng_collection.update_many(
                {"channel_configs.type": "slack"},
                {"$set": {"channel_configs.$[elem].type": "slack-webhook"}},
                array_filters=[{"elem.type": "slack"}],
            )
            print(f"    Updated {result.modified_count} document(s)")

    # Migration 2: contacts field rename
    print("\n[2] Migrating contacts: 'slack_webhook' -> 'slack_webhook_url'")
    contacts_collection = db["contacts"]
    contacts_count = await contacts_collection.count_documents({"slack_webhook": {"$exists": True}})
    print(f"    Found {contacts_count} document(s)")

    if contacts_count > 0:
        if dry_run:
            cursor = contacts_collection.find({"slack_webhook": {"$exists": True}}, {"name": 1})
            async for doc in cursor:
                print(f"      Would migrate: {doc.get('name')}")
        else:
            result = await contacts_collection.update_many(
                {"slack_webhook": {"$exists": True}},
                {"$rename": {"slack_webhook": "slack_webhook_url"}},
            )
            print(f"    Updated {result.modified_count} document(s)")

    if dry_run:
        print("\nDry run complete. Run without --dry-run to apply changes.")
    else:
        print("\nMigration complete.")

    client.close()


if __name__ == "__main__":
    import sys
    dry_run = "--dry-run" in sys.argv
    asyncio.run(migrate(dry_run))
