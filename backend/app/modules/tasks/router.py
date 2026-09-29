"""Task routes, merchant channel only.

Paths follow the spec: `/team` and `/tasks` under `/api/v1/merchant`, which is where every other
live merchant endpoint sits. Mounted on that channel alone - tasks are staff talking to each
other about work, and there is no customer-facing view of them.

One flat permission, `tasks.view`, gates every route including the writes. That is the spec's
explicit decision, not an oversight: the screens are built so any staff member can create a task,
assign it to anyone and update anyone's, and they do not expect a `403` on somebody else's task.
Adding a `tasks.manage` split here would break screens quietly rather than protect anything.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep
from app.modules.tasks.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.modules.tasks.schemas import (
    CreateTaskRequest,
    PostTaskMessageRequest,
    TaskActivityResponse,
    TaskMessageResponse,
    TaskPageResponse,
    TaskResponse,
    TeamMemberResponse,
    UpdateTaskStatusRequest,
)
from app.modules.tasks.service import TaskFilters, TaskService
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

TaskIdPath = Annotated[str, Path(alias="taskId", max_length=20)]

_guards = [
    Depends(require_login_channel(LoginChannel.MERCHANT)),
    Depends(require_permission("tasks.view")),
]


def build_service(
    actor: ActorDep,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TaskService:
    """FastAPI caches `get_db_session` per request, so the actor and the service share one
    session and therefore one transaction."""
    return TaskService(session, actor)


ServiceDep = Annotated[TaskService, Depends(build_service)]

# The team directory is its own path, not `/tasks/team` - it is the merchant's staff list, reused
# by the task screens rather than owned by them.
team_router = APIRouter(prefix="/team", tags=["Merchant Tasks"])
router = APIRouter(prefix="/tasks", tags=["Merchant Tasks"])


@team_router.get(
    "",
    response_model=list[TeamMemberResponse],
    dependencies=_guards,
    responses=error_responses(401, 403),
    summary="Team members",
)
async def list_team(
    service: ServiceDep,
    search: Annotated[str | None, Query(description="Matches a name, case-insensitively.", max_length=120)] = None,
) -> list[TeamMemberResponse]:
    """Active staff of the caller's merchant, for the Assign To picker and `@mention` autocomplete.

    Deliberately the same shape as the `user` object auth already returns, minus permissions: the
    app derives the display title from `role` and picks an avatar colour from `id` itself, so
    sending either would be two sources for one thing.
    """
    return await service.members(search)


@router.get(
    "",
    response_model=TaskPageResponse,
    dependencies=_guards,
    responses=error_responses(401, 403),
    summary="List tasks",
)
async def list_tasks(
    service: ServiceDep,
    scope: Annotated[
        str | None,
        Query(description="`ALL` (default) | `MY` (assigned to me) | `ASSIGNED` (created by me) | `COMPLETED`.", max_length=20),
    ] = None,
    task_status: Annotated[
        list[str] | None, Query(alias="status", description="Repeatable; values are OR'd.")
    ] = None,
    priority: Annotated[list[str] | None, Query(description="Repeatable; values are OR'd.")] = None,
    due: Annotated[
        str | None, Query(description="`TODAY` | `TOMORROW` | `THIS_WEEK` | `OVERDUE`.", max_length=20)
    ] = None,
    search: Annotated[
        str | None, Query(description="Title, description, task id, creator or assignee name.", max_length=120)
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> TaskPageResponse:
    """The Tasks screen, always newest-activity first.

    Sort is fixed rather than a parameter: the list is a work queue, and what changed last is what
    the team needs to see.
    """
    return await service.list_tasks(
        TaskFilters(
            scope=scope,
            statuses=task_status,
            priorities=priority,
            due=due,
            search=search,
            page=page,
            page_size=page_size,
        )
    )


@router.post(
    "",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=_guards,
    responses=error_responses(401, 403, 422),
    summary="Create a task",
)
async def create_task(payload: CreateTaskRequest, service: ServiceDep) -> TaskResponse:
    """Raise a task and assign it.

    Every assignee must be active staff of the caller's merchant. Attachments are `fileId`s from
    `POST /documents`; their name, type and size are resolved server-side, never taken from the
    request. One notification goes to the shared merchant bucket - not one per assignee.
    """
    return await service.create(payload)


@router.get(
    "/{taskId}",
    response_model=TaskResponse,
    dependencies=_guards,
    responses=error_responses(401, 403, 404),
    summary="Task detail",
)
async def get_task(task_id: TaskIdPath, service: ServiceDep) -> TaskResponse:
    """One task. Another merchant's task is a 404, never a 403."""
    return await service.get(task_id)


@router.get(
    "/{taskId}/messages",
    response_model=list[TaskMessageResponse],
    dependencies=_guards,
    responses=error_responses(401, 403, 404),
    summary="Task thread",
)
async def list_messages(task_id: TaskIdPath, service: ServiceDep) -> list[TaskMessageResponse]:
    """The whole thread, oldest first - it is a chat feed, rendered top to bottom.

    `STATUS_CHANGE` entries are written by the server when somebody moves the status or the
    progress; a client never posts one.
    """
    return await service.messages(task_id)


@router.get(
    "/{taskId}/activity",
    response_model=list[TaskActivityResponse],
    dependencies=_guards,
    responses=error_responses(401, 403, 404),
    summary="Task activity",
)
async def list_activity(task_id: TaskIdPath, service: ServiceDep) -> list[TaskActivityResponse]:
    """The audit strip, oldest first. Rendered verbatim as "{actorName} {action}"."""
    return await service.activity(task_id)


@router.patch(
    "/{taskId}/status",
    response_model=TaskResponse,
    dependencies=_guards,
    responses=error_responses(401, 403, 404, 422),
    summary="Update status or progress",
)
async def update_status(
    task_id: TaskIdPath, payload: UpdateTaskStatusRequest, service: ServiceDep
) -> TaskResponse:
    """Move the status, the progress, or add a note - at least one of the three.

    Completing a task forces progress to 100 whatever the same request asked for. Each part that
    actually changes something writes its own thread entry and activity line; a field sent with
    the value it already has is a no-op rather than a duplicate row.
    """
    return await service.update_status(task_id, payload)


@router.post(
    "/{taskId}/messages",
    response_model=TaskMessageResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=_guards,
    responses=error_responses(401, 403, 404, 422),
    summary="Post an update",
)
async def post_message(
    task_id: TaskIdPath, payload: PostTaskMessageRequest, service: ServiceDep
) -> TaskMessageResponse:
    """Comment on a task, with `@mentions` and attachments.

    Text or attachments - one of the two must carry something. A mention whose user no longer
    resolves is dropped rather than failing the message: somebody can be deactivated between the
    name being typed and send being tapped, and losing what was written over that is the wrong
    trade. Only `userId` is trusted; the name is re-resolved server-side.
    """
    return await service.post_message(task_id, payload)
