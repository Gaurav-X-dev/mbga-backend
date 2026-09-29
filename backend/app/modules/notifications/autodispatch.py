"""Sending a queued notification without waiting for the worker.

The outbox split exists for a good reason: an order must not fail because Firebase is slow,
and a notification that could not be sent must not be lost. But it should not mean a
notification only moves when somebody remembers to run a script.

So the happy path is automatic. A request that queues a notification schedules a dispatch
the moment its response has gone out - the caller has already been answered, so nothing
waits on Firebase, and the push lands a moment later.

The worker stays, but its job changes: it is the **safety net**, not the delivery mechanism.
It picks up what a process restart interrupted, what a Firebase outage deferred, and
anything queued by something that is not an HTTP request at all.

Three rules this file keeps:

* **After the response, never during it.** The dispatch starts once the response is on the
  wire, so a slow Firebase never becomes a slow API.
* **Its own session.** The request's session is closed by the time this runs; borrowing it
  would use a connection that has gone home.
* **Never raises into anything.** A failed dispatch leaves the row queued for the worker,
  which is exactly the state the outbox is designed to handle.
"""

import asyncio
import logging
from contextvars import ContextVar

from app.config.app import get_settings

logger = logging.getLogger(__name__)

#: Set by `NotificationOutboxWriter.queue()` during a request. The flag rather than the rows
#: themselves: by the time the dispatch runs, the transaction has committed and the
#: dispatcher can find everything that is due for itself.
_queued: ContextVar[bool] = ContextVar("notifications_queued", default=False)

#: Tasks in flight, held so Python cannot garbage-collect a running task mid-send.
_in_flight: set[asyncio.Task] = set()

#: One project registry per event loop, so a busy minute does not mint a fresh OAuth token
#: per request. Keyed by loop because each client owns an HTTP connection pool bound to the
#: loop it was created on, and the test suite runs several.
_registries: dict[int, object] = {}


def mark_queued() -> None:
    """Record that this request queued at least one notification."""
    _queued.set(True)


def take_queued() -> bool:
    """Whether this request queued anything, clearing the flag as it reads it."""
    queued = _queued.get()
    if queued:
        _queued.set(False)
    return queued


def schedule_dispatch() -> None:
    """Kick off a delivery pass in the background, if there is anything to deliver.

    Fire-and-forget on purpose. The response has already been sent; there is nobody left to
    report a failure to, and the row is still in the outbox for the worker either way.
    """
    settings = get_settings()
    if not settings.fcm_enabled or not settings.fcm_auto_dispatch:
        return
    try:
        task = asyncio.create_task(_dispatch())
    except RuntimeError:
        # No running loop - a synchronous caller, or shutdown. The worker will pick it up.
        return
    # Held until it finishes; asyncio only keeps a weak reference to running tasks.
    _in_flight.add(task)
    task.add_done_callback(_in_flight.discard)


async def _dispatch() -> None:
    """One delivery pass, with its own session and a reused client. Swallows everything."""
    # Imported here rather than at module scope: this module is imported by the outbox
    # writer, which the business modules import, and pulling the FCM client in at that
    # point would make a notification dependency of every write in the system.
    from app.modules.notifications.dispatcher import NotificationDispatcher
    from app.modules.notifications.projects import FcmProjects
    from app.shared.database.session import AsyncSessionLocal

    settings = get_settings()
    try:
        key = id(asyncio.get_running_loop())
        projects = _registries.get(key)
        if projects is None:
            projects = FcmProjects(settings)
            _registries[key] = projects
        async with AsyncSessionLocal() as session:
            report = await NotificationDispatcher(session, projects).run(limit=settings.fcm_batch_size)
        if report.delivered or report.retrying:
            logger.info("Auto-dispatched notifications: %s", report.as_dict())
    except Exception:
        # Left queued deliberately. The worker retries, and a push that failed is never a
        # reason to make noise in a request that already succeeded. The registry is
        # dropped so a credential fixed on disk is picked up without a restart.
        _registries.pop(id(asyncio.get_running_loop()), None)
        logger.warning("Auto-dispatch failed; rows stay queued for the worker", exc_info=True)
