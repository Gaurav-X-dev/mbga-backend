"""Evaluate configured reminder rules; safe for overlapping systemd timer runs."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.app import get_settings
from app.modules.notifications.dispatcher import NotificationDispatcher
from app.modules.notifications.projects import FcmProjects
from app.modules.reminders.engine import ReminderEngine
from app.shared.database.session import AsyncSessionLocal


async def run_once():
    async with AsyncSessionLocal() as session:
        result = await ReminderEngine(session).run()
    settings = get_settings()
    projects = FcmProjects(settings) if settings.fcm_enabled else None
    try:
        async with AsyncSessionLocal() as session:
            sent = await NotificationDispatcher(session, projects).run(
                limit=settings.fcm_batch_size, entity_type="reminder"
            )
            result["dispatch"] = sent.as_dict()
    finally:
        if projects:
            await projects.aclose()
    return result


if __name__ == "__main__":
    print(asyncio.run(run_once()))
