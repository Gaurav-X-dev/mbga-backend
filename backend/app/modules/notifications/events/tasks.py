"""Task notifications (TASK_MANAGEMENT_SPEC #6, #7, #8).

All three go to the **shared merchant bucket**, never to an individual. The spec is explicit about
this: per-user targeting is deferred platform-wide (API_SPEC §15, "all staff share the merchant
bucket"), so addressing an assignee or a mentioned person directly would make tasks the one module
that does it differently - and the delivery would then be the only thing in the system that
depended on a mechanism nothing else has.

That is also why "{author} mentioned you" says *you* to a bucket several people read. It is the
spec's wording and the app's copy; changing it here would put the backend and the screens out of
step over a word.

One notification per API call. The mock fired a generic "Task updated" *in addition* to any
specific one, and two notifications for one tap is how a bell gets muted.
"""

from app.modules.notifications.events._base import INFO, MERCHANT, TASK, NotificationEvent


def task_assigned(merchant_id: str, task_id: str, task_title: str) -> NotificationEvent:
    """To staff: a new task exists."""
    return NotificationEvent(
        event_type="TASK_ASSIGNED",
        recipient_kind=MERCHANT,
        recipient_id=merchant_id,
        entity_type=TASK,
        entity_id=task_id,
        title="New task assigned",
        body=task_title,
        severity=INFO,
    )


def task_updated(merchant_id: str, task_id: str, task_title: str) -> NotificationEvent:
    """To staff: something moved on a task.

    Keyed on the task, so a task updated five times collapses onto one bell row rather than five.
    That is the right trade for this event: the row deep-links to the task, and whoever taps it
    sees the whole thread anyway.
    """
    return NotificationEvent(
        event_type="TASK_UPDATED",
        recipient_kind=MERCHANT,
        recipient_id=merchant_id,
        entity_type=TASK,
        entity_id=task_id,
        title="Task updated",
        body=task_title,
        severity=INFO,
    )


def task_completed(merchant_id: str, task_id: str, task_title: str) -> NotificationEvent:
    """To staff: it is done. Replaces the generic update for that call, never joins it."""
    return NotificationEvent(
        event_type="TASK_COMPLETED",
        recipient_kind=MERCHANT,
        recipient_id=merchant_id,
        entity_type=TASK,
        entity_id=task_id,
        title="Task marked completed",
        body=task_title,
        severity=INFO,
    )


def task_mention(merchant_id: str, task_id: str, author_name: str, excerpt: str) -> NotificationEvent:
    """To staff: somebody was named in an update.

    `excerpt` is the message text, or the task title when the message was attachment-only - a
    notification whose body is empty reads as a bug.
    """
    return NotificationEvent(
        event_type="TASK_MENTION",
        recipient_kind=MERCHANT,
        recipient_id=merchant_id,
        entity_type=TASK,
        entity_id=task_id,
        title=f"{author_name} mentioned you",
        body=excerpt,
        severity=INFO,
    )
