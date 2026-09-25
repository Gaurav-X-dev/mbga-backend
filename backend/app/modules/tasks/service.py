"""Task reads and writes.

One permission gates everything (`tasks.view`) and one rule confines everything: a task belongs to
a merchant, and `_scope()` is the only way any query starts. Another merchant's task is a 404, not
a 403, for the same reason as orders and slips - `TASK-000123` is guessable by design.

Inside a merchant there is deliberately **no** ownership rule. Any staff member may create a task,
assign it to anyone, update anyone's task and post on it. The spec spells this out and says not to
add a restriction silently, because the screens do not expect a 403 on somebody else's task.

Every write is one transaction that does four things together: change the task, write the thread
entry, write the activity line, and queue the notification. A status change whose activity row
failed to land would leave a timeline that cannot explain the state it is showing.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import status as http_status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.models import CustomerDocument
from app.modules.notifications.events import tasks as task_events
from app.modules.tasks import validation
from app.modules.tasks.constants import (
    ACTION_CREATED,
    ACTION_POSTED,
    COMPLETION_PROGRESS,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    AttachmentKind,
    DueFilter,
    TaskMessageKind,
    TaskScope,
    TaskStatus,
    action_assigned,
    action_mentioned,
    action_progress,
    action_status,
    action_uploaded,
    message_progress,
    message_status,
)
from app.modules.tasks.models import (
    Task,
    TaskActivity,
    TaskAssignee,
    TaskAttachment,
    TaskMessage,
    TaskMessageMention,
)
from app.modules.tasks.numbering import TaskNumberAllocator, new_attachment_id, new_message_id
from app.modules.tasks.schemas import (
    AttachmentRequest,
    CreateTaskRequest,
    MentionResponse,
    PostTaskMessageRequest,
    ProgressChange,
    StatusChange,
    TaskActivityResponse,
    TaskAttachmentResponse,
    TaskMessageResponse,
    TaskPageResponse,
    TaskResponse,
    TeamMemberResponse,
    UpdateTaskStatusRequest,
)
from app.modules.tasks.team import TeamDirectory
from app.shared.business.actor import BusinessActor
from app.shared.date_time.business_calendar import business_today
from app.shared.exceptions.api_error import ApiError
from app.shared.notifications.outbox import NotificationOutboxWriter


def _not_found() -> ApiError:
    return ApiError("TASK_NOT_FOUND", http_status.HTTP_404_NOT_FOUND)


@dataclass
class TaskFilters:
    """Spec #2's query. Everything optional; `scope` defaults to ALL."""

    scope: str | None = None
    statuses: list[str] | None = None
    priorities: list[str] | None = None
    due: str | None = None
    search: str | None = None
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE


class TaskService:
    def __init__(self, session: AsyncSession, actor: BusinessActor) -> None:
        self.session = session
        self.actor = actor
        self.merchant_id = actor.require_merchant_id()
        self.team = TeamDirectory(session, self.merchant_id)
        self.notifications = NotificationOutboxWriter(session)

    # --- The people picker --------------------------------------------------------------------

    async def members(self, search: str | None = None) -> list[TeamMemberResponse]:
        """Spec #1. The merchant's active staff, reused rather than duplicated."""
        return [
            TeamMemberResponse(
                id=member.id, name=member.name, role=member.role, branch_name=member.branch_name
            )
            for member in await self.team.members(search=search)
        ]

    # --- Reads --------------------------------------------------------------------------------

    async def list_tasks(self, filters: TaskFilters) -> TaskPageResponse:
        """Spec #2. Always `updatedAt` descending, paged.

        The count runs against the same filtered statement rather than a second hand-built one -
        two queries that are supposed to agree and are written separately eventually do not.
        """
        statement = self._filtered(filters)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(statement.with_only_columns(Task.id).subquery())
            )
            or 0
        )
        page = max(filters.page, 1)
        size = min(max(filters.page_size, 1), MAX_PAGE_SIZE)
        rows = list(
            await self.session.scalars(
                statement.order_by(Task.updated_at.desc(), Task.task_number.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        )
        return TaskPageResponse(
            items=await self._views(rows), page=page, page_size=size, total=total
        )

    async def get(self, task_id: str) -> TaskResponse:
        return (await self._views([await self._owned(task_id)]))[0]

    async def messages(self, task_id: str) -> list[TaskMessageResponse]:
        """Spec #4. Oldest first - it is a chat feed, rendered top to bottom."""
        task = await self._owned(task_id)
        rows = list(
            await self.session.scalars(
                select(TaskMessage)
                .where(TaskMessage.task_id == task.id)
                .order_by(TaskMessage.created_at, TaskMessage.id)
            )
        )
        mentions = await self._mentions([row.id for row in rows])
        attachments = await self._attachments_by_message(task.id)
        return [_message_view(row, mentions.get(row.id, []), attachments.get(row.id, [])) for row in rows]

    async def activity(self, task_id: str) -> list[TaskActivityResponse]:
        """Spec #5. Oldest first: it reads as a story from the top."""
        task = await self._owned(task_id)
        rows = list(
            await self.session.scalars(
                select(TaskActivity)
                .where(TaskActivity.task_id == task.id)
                .order_by(TaskActivity.created_at, TaskActivity.id)
            )
        )
        return [
            TaskActivityResponse(
                id=str(row.id),
                task_id=row.task_id,
                at=row.created_at,
                actor_name=row.actor_name,
                action=row.action,
            )
            for row in rows
        ]

    # --- Creating -----------------------------------------------------------------------------

    async def create(self, payload: CreateTaskRequest) -> TaskResponse:
        """Spec #6. One transaction: task, assignees, attachments, activity, notification."""
        title = validation.check_create(payload, today=business_today())
        assignees = await self._resolve_assignees(payload.assigned_user_ids)
        now = datetime.now(UTC)

        number, task_id = await TaskNumberAllocator(self.session).allocate()
        task = Task(
            id=task_id,
            task_number=number,
            merchant_id=self.merchant_id,
            title=title,
            description=(payload.description or "").strip(),
            status=TaskStatus.NOT_STARTED.value,
            priority=payload.priority.value,
            progress=0,
            category=payload.category.value if payload.category else None,
            related_type=payload.related_type.value if payload.related_type else None,
            related_id=(payload.related_id or "").strip() or None,
            related_label=(payload.related_label or "").strip() or None,
            created_by_user_id=self.actor.user_id,
            created_by_name=self.actor.display_name,
            due_date=payload.due_date,
            due_time=payload.due_time,
            message_count=0,
            created_at=now,
            updated_at=now,
        )
        self.session.add(task)
        # Flushed before the children: they are linked by foreign keys but by no ORM
        # relationship, so the unit of work does not order the inserts for us.
        await self.session.flush()

        for user_id in payload.assigned_user_ids:
            self.session.add(TaskAssignee(task_id=task.id, user_id=user_id, assigned_at=now))

        # "created this task" first, so the timeline starts where the task did. The spec's
        # behaviour list names only the assignment line, but its own example response for #5
        # opens with this one - and an activity strip whose first entry is an assignment reads
        # as though the task appeared from nowhere.
        self._log(task.id, ACTION_CREATED, now)
        self._log(task.id, action_assigned([assignees[user_id] for user_id in payload.assigned_user_ids]), now)
        await self._attach(task, payload.attachments, message_id=None, now=now)

        # One notification per creation, into the shared merchant bucket - not one per assignee.
        # Per-user targeting is deferred platform-wide (spec §15), and faking it here would make
        # this the only module that addresses staff individually.
        self.notifications.queue(task_events.task_assigned(self.merchant_id, task.id, task.title))
        await self.session.commit()
        return await self.get(task.id)

    # --- Updating -----------------------------------------------------------------------------

    async def update_status(self, task_id: str, payload: UpdateTaskStatusRequest) -> TaskResponse:
        """Spec #7. Status, progress and a note, in that order, each only if it changes something.

        The ordering is the spec's and it matters: completing a task forces progress to 100, so
        the progress step has to see the value the status step just set rather than the one the
        request asked for.
        """
        note = validation.check_update(payload)
        task = await self._owned(task_id)
        now = datetime.now(UTC)
        completed = False

        if payload.status is not None and payload.status.value != task.status:
            previous = task.status
            task.status = payload.status.value
            completed = payload.status is TaskStatus.COMPLETED
            if completed:
                # Whatever `progress` the same request asked for. A task that is done but sitting
                # at 40% is a number nobody believes.
                task.progress = COMPLETION_PROGRESS
            self._thread(
                task,
                kind=TaskMessageKind.STATUS_CHANGE,
                text=message_status(payload.status, note),
                now=now,
                status_from=previous,
                status_to=task.status,
            )
            self._log(task.id, action_status(payload.status), now)

        # Skipped entirely when the same call completed the task: the spec forces progress to 100
        # "regardless of any progress also sent in the same request", and letting this branch run
        # would see 100 != 40 and quietly put it back to 40.
        if not completed and payload.progress is not None and payload.progress != task.progress:
            previous_progress = task.progress
            task.progress = payload.progress
            self._thread(
                task,
                kind=TaskMessageKind.STATUS_CHANGE,
                text=message_progress(payload.progress),
                now=now,
                progress_from=previous_progress,
                progress_to=payload.progress,
            )
            self._log(task.id, action_progress(payload.progress), now)

        if note and payload.status is None:
            # A plain note, not context tacked onto a status change - that one is already in the
            # status message above, and writing it twice would show it twice in the thread.
            self._thread(task, kind=TaskMessageKind.COMMENT, text=note, now=now)
            task.message_count += 1
            self._log(task.id, ACTION_POSTED, now)

        task.updated_at = now
        # Exactly one notification per call. The mock fired a generic "Task updated" *in addition*
        # to any specific one; two notifications for one tap is how a bell gets muted.
        #
        # Repeatable, because the notification has to carry the **task** id - tapping it opens the
        # task - so a second update is the same outbox key. It refreshes the pending row rather
        # than failing on it, which also means a task updated five times is one unread row.
        await self.notifications.queue_repeatable(
            task_events.task_completed(self.merchant_id, task.id, task.title)
            if completed
            else task_events.task_updated(self.merchant_id, task.id, task.title)
        )
        await self.session.commit()
        return await self.get(task.id)

    # --- Posting -------------------------------------------------------------------------------

    async def post_message(self, task_id: str, payload: PostTaskMessageRequest) -> TaskMessageResponse:
        """Spec #8. A comment, its mentions and its attachments, in one transaction."""
        text = validation.check_message(payload)
        task = await self._owned(task_id)
        now = datetime.now(UTC)

        message = self._thread(task, kind=TaskMessageKind.COMMENT, text=text, now=now)
        await self.session.flush()

        mentioned = await self._resolve_mentions(payload.mentions)
        for user_id in mentioned:
            self.session.add(TaskMessageMention(message_id=message.id, user_id=user_id))

        attachments = await self._attach(task, payload.attachments, message_id=message.id, now=now)

        task.message_count += 1
        task.updated_at = now
        self._log(task.id, ACTION_POSTED, now)
        if mentioned:
            names = await self.team.names(list(mentioned))
            self._log(task.id, action_mentioned([names[user_id] for user_id in mentioned]), now)
        for attachment in attachments:
            self._log(task.id, action_uploaded(attachment.name), now)

        if mentioned:
            # Repeatable for the same reason as an update: the row deep-links to the task, so
            # every mention on that task shares one key.
            await self.notifications.queue_repeatable(
                task_events.task_mention(
                    self.merchant_id,
                    task.id,
                    self.actor.display_name,
                    # Attachment-only messages have no text to quote, so the task title stands in.
                    text or task.title,
                )
            )
        await self.session.commit()

        names = await self.team.names(list(mentioned))
        return _message_view(
            message,
            [MentionResponse(user_id=user_id, name=names.get(user_id, "")) for user_id in mentioned],
            [_attachment_view(row) for row in attachments],
        )

    # --- Writing helpers -------------------------------------------------------------------------

    def _thread(
        self,
        task: Task,
        *,
        kind: TaskMessageKind,
        text: str,
        now: datetime,
        status_from: str | None = None,
        status_to: str | None = None,
        progress_from: int | None = None,
        progress_to: int | None = None,
    ) -> TaskMessage:
        message = TaskMessage(
            id=new_message_id(),
            task_id=task.id,
            kind=kind.value,
            author_user_id=self.actor.user_id,
            author_name=self.actor.display_name,
            text=text,
            status_change_from=status_from,
            status_change_to=status_to,
            progress_change_from=progress_from,
            progress_change_to=progress_to,
            created_at=now,
        )
        self.session.add(message)
        return message

    def _log(self, task_id: str, action: str, now: datetime) -> None:
        self.session.add(
            TaskActivity(
                task_id=task_id,
                actor_user_id=self.actor.user_id,
                actor_name=self.actor.display_name,
                action=action,
                created_at=now,
            )
        )

    async def _attach(
        self,
        task: Task,
        requested: list[AttachmentRequest],
        *,
        message_id: str | None,
        now: datetime,
    ) -> list[TaskAttachment]:
        """Turn uploaded `fileId`s into attachments, resolving their metadata server-side.

        Name, type and size come from the documents table, never from the request. A client that
        could set its own `size` would make the file tab lie about what it is offering to open.
        """
        if not requested:
            return []
        documents = await self._documents({item.file_id for item in requested})
        rows: list[TaskAttachment] = []
        for item in requested:
            document = documents.get(item.file_id)
            if document is None:
                raise validation.invalid(
                    "attachments", "file_not_found", "This file is no longer available. Upload it again."
                )
            row = TaskAttachment(
                id=new_attachment_id(),
                task_id=task.id,
                message_id=message_id,
                document_file_id=item.file_id,
                kind=_kind_of(item.kind, document.mime_type),
                name=document.original_filename or "attachment",
                mime_type=document.mime_type,
                size_bytes=document.file_size,
                uploaded_by_user_id=self.actor.user_id,
                uploaded_by_name=self.actor.display_name,
                uploaded_at=now,
            )
            self.session.add(row)
            rows.append(row)
            if message_id is None:
                # Creation-time attachments get their own activity line; a message's attachments
                # are logged by the caller, after the "posted an update" line.
                self._log(task.id, action_uploaded(row.name), now)
        return rows

    async def _documents(self, file_ids: set[str]) -> dict[str, CustomerDocument]:
        """The uploader's own files, from this merchant.

        Scoped, not looked up blindly: an unscoped `fileId` lookup would let one merchant attach
        another's KYC document to a task and read its name and size off the file tab.
        """
        rows = list(
            await self.session.scalars(
                select(CustomerDocument).where(
                    CustomerDocument.file_id.in_(file_ids),
                    CustomerDocument.uploaded_by_user_id == self.actor.user_id,
                    CustomerDocument.merchant_id == self.merchant_id,
                )
            )
        )
        return {row.file_id: row for row in rows}

    async def _resolve_assignees(self, user_ids: list[str]) -> dict[str, str]:
        """Every assignee must be active staff of this merchant. Returns id -> display name."""
        active = await self.team.active_ids(user_ids)
        missing = [user_id for user_id in user_ids if user_id not in active]
        if missing:
            raise validation.invalid(
                "assignedUserIds",
                "assignee_not_found",
                "One of the people chosen is no longer on the team.",
            )
        return await self.team.names(user_ids)

    async def _resolve_mentions(self, mentions: list) -> list[str]:
        """Resolvable mentions, in the order sent, de-duplicated.

        An unresolvable one is **dropped rather than rejected**: somebody can be deactivated
        between the moment their name is typed and the moment send is tapped, and losing what the
        person wrote over that would be the wrong trade.
        """
        requested = list(dict.fromkeys(item.user_id for item in mentions))
        active = await self.team.active_ids(requested)
        return [user_id for user_id in requested if user_id in active]

    # --- Reading helpers ---------------------------------------------------------------------------

    def _scope(self, statement: Select) -> Select:
        """Every task query starts here. Applied as a `WHERE`, never as a later filter."""
        return statement.where(Task.merchant_id == self.merchant_id)

    async def _owned(self, task_id: str) -> Task:
        task = await self.session.scalar(self._scope(select(Task)).where(Task.id == task_id))
        if task is None:
            raise _not_found()
        return task

    def _filtered(self, filters: TaskFilters) -> Select:
        statement = self._scope(select(Task))
        statement = self._apply_scope(statement, filters.scope)
        if filters.statuses:
            statement = statement.where(Task.status.in_([value.upper() for value in filters.statuses]))
        if filters.priorities:
            statement = statement.where(Task.priority.in_([value.upper() for value in filters.priorities]))
        statement = self._apply_due(statement, filters.due)
        return self._apply_search(statement, filters.search)

    def _apply_scope(self, statement: Select, scope: str | None) -> Select:
        """The list screen's four tabs.

        `COMPLETED` deliberately ignores who created or was assigned: the tab is "what is done
        here", not "what I finished".
        """
        value = (scope or TaskScope.ALL.value).upper()
        if value == TaskScope.MY.value:
            mine = select(TaskAssignee.task_id).where(TaskAssignee.user_id == self.actor.user_id)
            return statement.where(Task.id.in_(mine))
        if value == TaskScope.ASSIGNED.value:
            return statement.where(Task.created_by_user_id == self.actor.user_id)
        if value == TaskScope.COMPLETED.value:
            return statement.where(Task.status == TaskStatus.COMPLETED.value)
        return statement

    @staticmethod
    def _apply_due(statement: Select, due: str | None) -> Select:
        """Date windows on the business (IST) calendar, so "today" is the user's today."""
        if not due:
            return statement
        value = due.upper()
        today = business_today()
        if value == DueFilter.TODAY.value:
            return statement.where(Task.due_date == today)
        if value == DueFilter.TOMORROW.value:
            return statement.where(Task.due_date == today + timedelta(days=1))
        if value == DueFilter.THIS_WEEK.value:
            # Through Sunday, counting today. Monday is 0, so this lands on the coming weekend.
            return statement.where(
                Task.due_date >= today, Task.due_date <= today + timedelta(days=6 - today.weekday())
            )
        if value == DueFilter.OVERDUE.value:
            # A completed task is never overdue, however late it was finished.
            return statement.where(
                Task.due_date < today, Task.status != TaskStatus.COMPLETED.value
            )
        # An unrecognised chip shows an empty list rather than an error dialog.
        return statement.where(False)

    def _apply_search(self, statement: Select, search: str | None) -> Select:
        """Title, description, task id, or any assignee's name (spec #2)."""
        term = (search or "").strip()
        if not term:
            return statement
        pattern = f"%{term}%"
        from app.modules.users.models import User

        by_assignee = (
            select(TaskAssignee.task_id)
            .join(User, User.id == TaskAssignee.user_id)
            .where(or_(User.full_name.like(pattern), User.username.like(pattern)))
        )
        return statement.where(
            or_(
                Task.title.like(pattern),
                Task.description.like(pattern),
                Task.id.like(pattern),
                Task.created_by_name.like(pattern),
                Task.id.in_(by_assignee),
            )
        )

    async def _views(self, tasks: list[Task]) -> list[TaskResponse]:
        """Render a page of tasks with their assignees and attachments, in two queries each.

        Batched rather than per row: the list is the module's busiest screen, and a per-card query
        for assignees is the N+1 that makes it feel slow at thirty tasks.
        """
        if not tasks:
            return []
        ids = [task.id for task in tasks]
        assignees: dict[str, list[str]] = {task_id: [] for task_id in ids}
        for row in await self.session.execute(
            select(TaskAssignee.task_id, TaskAssignee.user_id)
            .where(TaskAssignee.task_id.in_(ids))
            .order_by(TaskAssignee.assigned_at, TaskAssignee.user_id)
        ):
            assignees[row.task_id].append(row.user_id)

        attachments: dict[str, list[TaskAttachmentResponse]] = {task_id: [] for task_id in ids}
        for row in await self.session.scalars(
            select(TaskAttachment)
            .where(TaskAttachment.task_id.in_(ids))
            .order_by(TaskAttachment.uploaded_at, TaskAttachment.id)
        ):
            attachments[row.task_id].append(_attachment_view(row))

        return [_task_view(task, assignees[task.id], attachments[task.id]) for task in tasks]

    async def _mentions(self, message_ids: list[str]) -> dict[str, list[MentionResponse]]:
        """Mentions for a whole thread, with names resolved now rather than as stored."""
        if not message_ids:
            return {}
        rows = list(
            await self.session.execute(
                select(TaskMessageMention.message_id, TaskMessageMention.user_id).where(
                    TaskMessageMention.message_id.in_(message_ids)
                )
            )
        )
        names = await self.team.names({row.user_id for row in rows})
        found: dict[str, list[MentionResponse]] = {}
        for row in rows:
            found.setdefault(row.message_id, []).append(
                MentionResponse(user_id=row.user_id, name=names.get(row.user_id, ""))
            )
        return found

    async def _attachments_by_message(self, task_id: str) -> dict[str, list[TaskAttachmentResponse]]:
        rows = list(
            await self.session.scalars(
                select(TaskAttachment)
                .where(TaskAttachment.task_id == task_id, TaskAttachment.message_id.is_not(None))
                .order_by(TaskAttachment.uploaded_at, TaskAttachment.id)
            )
        )
        found: dict[str, list[TaskAttachmentResponse]] = {}
        for row in rows:
            found.setdefault(row.message_id, []).append(_attachment_view(row))
        return found


def _kind_of(_requested: AttachmentKind, mime_type: str) -> str:
    """The stored bytes decide, not the client.

    A PDF declared `IMAGE` would be rendered inline in the chat grid as a broken thumbnail. The
    mime type is trustworthy because the upload endpoint sniffs it from the bytes, so the client's
    `kind` is accepted as a hint and then overruled by what was actually stored.
    """
    return (
        AttachmentKind.IMAGE.value
        if mime_type.lower().startswith("image/")
        else AttachmentKind.FILE.value
    )


def _attachment_view(row: TaskAttachment) -> TaskAttachmentResponse:
    return TaskAttachmentResponse(
        id=row.id,
        kind=AttachmentKind(row.kind),
        # Images need a URL the chat grid can render immediately; files are opened on tap, so the
        # app resolves a short-lived URL then - the same lazy path the KYC screens already use.
        uri=f"/api/v1/merchant/documents/{row.document_file_id}/content"
        if row.kind == AttachmentKind.IMAGE.value
        else None,
        name=row.name,
        mime_type=row.mime_type,
        size=row.size_bytes,
        uploaded_by=row.uploaded_by_user_id,
        uploaded_by_name=row.uploaded_by_name,
        uploaded_at=row.uploaded_at,
        file_id=row.document_file_id,
    )


def _task_view(
    task: Task, assignee_ids: list[str], attachments: list[TaskAttachmentResponse]
) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        title=task.title,
        description=task.description or "",
        status=TaskStatus(task.status),
        priority=task.priority,
        progress=task.progress,
        category=task.category,
        assigned_user_ids=assignee_ids,
        created_by_user_id=task.created_by_user_id,
        created_by_name=task.created_by_name,
        due_date=task.due_date,
        due_time=task.due_time,
        related_type=task.related_type,
        related_id=task.related_id,
        related_label=task.related_label,
        attachments=attachments,
        message_count=task.message_count,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _message_view(
    row: TaskMessage,
    mentions: list[MentionResponse],
    attachments: list[TaskAttachmentResponse],
) -> TaskMessageResponse:
    return TaskMessageResponse(
        id=row.id,
        task_id=row.task_id,
        kind=row.kind,
        author_id=row.author_user_id,
        author_name=row.author_name,
        text=row.text or "",
        mentions=mentions,
        attachments=attachments,
        status_change=(
            StatusChange(from_=TaskStatus(row.status_change_from), to=TaskStatus(row.status_change_to))
            if row.status_change_from and row.status_change_to
            else None
        ),
        progress_change=(
            ProgressChange(from_=row.progress_change_from, to=row.progress_change_to)
            if row.progress_change_from is not None and row.progress_change_to is not None
            else None
        ),
        created_at=row.created_at,
    )

