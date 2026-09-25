"""A task's life: raised, worked on, talked about, finished.

Most of what can go wrong in this module is a **side effect that did not happen**. A status change
that leaves no thread entry, a mention that logs nobody, a note that does not bump the message
count - each of those still returns 200 and looks fine until somebody opens the task a week later
and the story does not add up. So these tests check the trail as much as the state.
"""

import pytest

from tests.integration.tasks.conftest import (
    TASKS,
    activity,
    body,
    colleague,
    create_task,
    get_task,
    messages,
    task_staff,
    team_of,
    tomorrow,
    upload,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


# --- Creating ------------------------------------------------------------------------------------


async def test_a_new_task_starts_not_started_at_zero(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)

    task = await create_task(env, token, assignedUserIds=[priya.id])

    assert task["status"] == "NOT_STARTED"
    assert task["progress"] == 0
    assert task["messageCount"] == 0
    assert task["assignedUserIds"] == [priya.id]
    assert task["createdByName"] == "Rajesh Verma"
    assert task["id"].startswith("TASK-")


async def test_task_ids_are_sequential_and_unique(env):
    """`TASK-000123` is the primary key, so the counter behind it is platform-wide.

    A per-merchant counter would give every merchant a `TASK-000001` and the second one to arrive
    would collide - which is exactly what it did before this was fixed.
    """
    token, _merchant, _creator, priya, _amit = await team_of(env)
    other_token, other_merchant, _c2 = await task_staff(env)
    outsider = await colleague(env, other_merchant, "Someone Else")

    mine = [(await create_task(env, token, assignedUserIds=[priya.id]))["id"] for _ in range(3)]
    theirs = (await create_task(env, other_token, assignedUserIds=[outsider.id]))["id"]

    assert mine == sorted(mine), "ids climb"
    assert all(task_id.startswith("TASK-") for task_id in mine)
    assert theirs not in mine, "two merchants never share an id"


async def test_a_task_can_be_assigned_to_several_people(env):
    token, _merchant, _creator, priya, amit = await team_of(env)

    task = await create_task(env, token, assignedUserIds=[priya.id, amit.id])

    assert set(task["assignedUserIds"]) == {priya.id, amit.id}


async def test_creation_writes_the_opening_activity(env):
    """The strip has to start where the task did, or it reads as though it appeared from nowhere."""
    token, _merchant, _creator, priya, amit = await team_of(env)

    task = await create_task(env, token, assignedUserIds=[priya.id, amit.id])

    assert await activity(env, token, task["id"]) == [
        "created this task",
        "assigned this task to Priya Nair, Amit Verma",
    ]


async def test_a_linked_record_is_kept_whole(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)

    task = await create_task(
        env,
        token,
        assignedUserIds=[priya.id],
        relatedType="CUSTOMER",
        relatedId="CUST-0045",
        relatedLabel="Sharma Traders",
    )

    assert (task["relatedType"], task["relatedId"], task["relatedLabel"]) == (
        "CUSTOMER",
        "CUST-0045",
        "Sharma Traders",
    )


async def test_a_half_filled_link_is_refused(env):
    """A type with no id is a chip the app renders and cannot open."""
    token, _merchant, _creator, priya, _amit = await team_of(env)

    response = await env.post(
        TASKS, token, body(assignedUserIds=[priya.id], relatedType="CUSTOMER")
    )

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "relatedType"


async def test_a_task_must_be_assigned_to_somebody(env):
    """A task on nobody is a note, and no screen can show one."""
    token, _merchant, _creator, _priya, _amit = await team_of(env)

    response = await env.post(TASKS, token, body(assignedUserIds=[]))

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "assignedUserIds"


async def test_a_task_cannot_be_backdated(env):
    """Otherwise the OVERDUE filter claims a brand-new task is already late."""
    token, _merchant, _creator, priya, _amit = await team_of(env)

    response = await env.post(
        TASKS, token, body(assignedUserIds=[priya.id], dueDate="2020-01-01")
    )

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "dueDate"


async def test_somebody_from_another_merchant_cannot_be_assigned(env):
    """The picker only offers your own staff; the API does not take that on trust."""
    token, _merchant, _creator, _priya, _amit = await team_of(env)
    _other_token, other_merchant, _other_creator = await task_staff(env)
    outsider = await colleague(env, other_merchant, "Outsider")

    response = await env.post(TASKS, token, body(assignedUserIds=[outsider.id]))

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "assignedUserIds"


# --- Status and progress ------------------------------------------------------------------------


async def patch(env, token: str, task_id: str, **payload):
    return await env.client.patch(
        f"{TASKS}/{task_id}/status", json=payload, headers={"Authorization": f"Bearer {token}"}
    )


async def test_a_status_change_writes_a_thread_entry_and_an_activity_line(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])

    response = await patch(env, token, task["id"], status="IN_PROGRESS")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "IN_PROGRESS"
    thread = await messages(env, token, task["id"])
    assert thread[0]["kind"] == "STATUS_CHANGE"
    assert thread[0]["text"] == "changed status to In Progress"
    assert thread[0]["statusChange"] == {"from": "NOT_STARTED", "to": "IN_PROGRESS"}
    assert "changed status to In Progress" in await activity(env, token, task["id"])


async def test_a_note_sent_with_a_status_change_is_appended_not_lost(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])

    await patch(env, token, task["id"], status="ON_HOLD", note="Waiting on the BPCL truck.")

    thread = await messages(env, token, task["id"])
    assert thread[0]["text"] == "changed status to On Hold — Waiting on the BPCL truck."
    assert len(thread) == 1, "the note is part of the status entry, not a second one"


async def test_a_progress_change_is_its_own_entry(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])

    await patch(env, token, task["id"], progress=40)

    thread = await messages(env, token, task["id"])
    assert thread[0]["text"] == "updated progress to 40%"
    assert thread[0]["progressChange"] == {"from": 0, "to": 40}


async def test_completing_forces_progress_to_a_hundred(env):
    """A task that is done but sitting at 40% is a number nobody believes."""
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])

    response = await patch(env, token, task["id"], status="COMPLETED", progress=40)

    assert response.json()["progress"] == 100
    assert response.json()["status"] == "COMPLETED"


async def test_completing_says_marked_rather_than_changed(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])

    await patch(env, token, task["id"], status="COMPLETED")

    assert "marked this task Completed" in await activity(env, token, task["id"])


async def test_a_plain_note_is_a_comment_and_counts(env):
    """No status sent, so it is somebody talking rather than context on a change."""
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])

    await patch(env, token, task["id"], note="Started on the 19 KG rack.")

    thread = await messages(env, token, task["id"])
    assert thread[0]["kind"] == "COMMENT"
    assert thread[0]["text"] == "Started on the 19 KG rack."
    assert (await get_task(env, token, task["id"]))["messageCount"] == 1
    assert "posted an update" in await activity(env, token, task["id"])


async def test_sending_a_value_it_already_has_changes_nothing(env):
    """A no-op must not put a row in the thread saying something happened."""
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])

    response = await patch(env, token, task["id"], status="NOT_STARTED", progress=0)

    assert response.status_code == 200
    assert await messages(env, token, task["id"]) == []


async def test_an_empty_update_is_refused(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])

    response = await patch(env, token, task["id"])

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "status"


async def test_progress_outside_the_range_is_refused(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])

    for value in (-1, 101):
        response = await patch(env, token, task["id"], progress=value)
        assert response.status_code == 422, value
        assert response.json()["detail"]["fields"][0]["field"] == "progress"


async def test_a_task_can_be_updated_twice(env):
    """The bell row is keyed on the task, so a second update used to be a duplicate-key 500.

    It refreshes the pending notification instead - which is also the better bell behaviour: one
    unread row saying the task moved, not five identical ones.
    """
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])

    first = await patch(env, token, task["id"], progress=25)
    second = await patch(env, token, task["id"], progress=60)
    third = await patch(env, token, task["id"], status="COMPLETED")

    assert [first.status_code, second.status_code, third.status_code] == [200, 200, 200]
    assert (await get_task(env, token, task["id"]))["progress"] == 100


# --- The thread ------------------------------------------------------------------------------------


async def post(env, token: str, task_id: str, **payload):
    return await env.post(f"{TASKS}/{task_id}/messages", token, payload)


async def test_posting_an_update(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])

    response = await post(env, token, task["id"], text="Counted 180 of 200 so far.")

    assert response.status_code == 201, response.text
    message = response.json()
    assert message["kind"] == "COMMENT"
    assert message["authorName"] == "Rajesh Verma"
    assert message["text"] == "Counted 180 of 200 so far."
    assert (await get_task(env, token, task["id"]))["messageCount"] == 1


async def test_a_mention_is_recorded_and_logged(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])

    response = await post(
        env,
        token,
        task["id"],
        text="@Priya Nair please review the count.",
        mentions=[{"userId": priya.id, "name": "Priya Nair"}],
    )

    assert response.json()["mentions"] == [{"userId": priya.id, "name": "Priya Nair"}]
    assert "mentioned Priya Nair" in await activity(env, token, task["id"])


async def test_a_mention_name_is_re_resolved_not_trusted(env):
    """The client's copy can be stale, and a log that quotes it can be written to say anything."""
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])

    response = await post(
        env,
        token,
        task["id"],
        text="check this",
        mentions=[{"userId": priya.id, "name": "Somebody Else"}],
    )

    assert response.json()["mentions"][0]["name"] == "Priya Nair"


async def test_an_unresolvable_mention_is_dropped_not_fatal(env):
    """Somebody can be deactivated between the name being typed and send being tapped."""
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])

    response = await post(
        env,
        token,
        task["id"],
        text="still worth saying",
        mentions=[{"userId": "gone-user-id", "name": "Ghost"}],
    )

    assert response.status_code == 201, "the message survives"
    assert response.json()["mentions"] == []
    assert response.json()["text"] == "still worth saying"


async def test_an_empty_message_is_refused(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])

    response = await post(env, token, task["id"], text="   ")

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["message"] == "Write an update or attach a file."


async def test_the_thread_is_oldest_first(env):
    """It is a chat feed, rendered top to bottom."""
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])

    await post(env, token, task["id"], text="first")
    await patch(env, token, task["id"], status="IN_PROGRESS")
    await post(env, token, task["id"], text="third")

    assert [row["text"] for row in await messages(env, token, task["id"])] == [
        "first",
        "changed status to In Progress",
        "third",
    ]


# --- Attachments -------------------------------------------------------------------------------------


async def test_a_file_attached_at_creation_shows_on_the_task(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    uploaded = await upload(env, token, name="stock_count.png")

    task = await create_task(
        env,
        token,
        assignedUserIds=[priya.id],
        attachments=[{"fileId": uploaded["fileId"], "kind": "IMAGE"}],
    )

    assert len(task["attachments"]) == 1
    attachment = task["attachments"][0]
    assert attachment["name"] == "stock_count.png"
    assert attachment["mimeType"] == "image/png"
    assert attachment["kind"] == "IMAGE"
    assert attachment["uri"], "an image needs a URL the chat grid can render immediately"
    assert "uploaded stock_count.png" in await activity(env, token, task["id"])


async def test_the_file_metadata_comes_from_the_store_not_the_request(env):
    """A client that could set its own size would make the file tab lie about what it opens."""
    token, _merchant, _creator, priya, _amit = await team_of(env)
    uploaded = await upload(env, token, name="real_name.png")

    task = await create_task(
        env,
        token,
        assignedUserIds=[priya.id],
        attachments=[{"fileId": uploaded["fileId"], "kind": "FILE"}],
    )

    attachment = task["attachments"][0]
    assert attachment["name"] == "real_name.png"
    assert attachment["size"] == uploaded["size"]
    # Declared FILE, but the stored bytes are a PNG - so it renders inline rather than as a
    # broken thumbnail.
    assert attachment["kind"] == "IMAGE"


async def test_a_message_attachment_appears_in_both_places(env):
    """One row serves the chat bubble and the task's file tab, so the two cannot drift."""
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])
    uploaded = await upload(env, token, name="shelf.png")

    posted = await post(
        env,
        token,
        task["id"],
        text="here it is",
        attachments=[{"fileId": uploaded["fileId"], "kind": "IMAGE"}],
    )

    assert len(posted.json()["attachments"]) == 1
    assert len((await get_task(env, token, task["id"]))["attachments"]) == 1
    assert len((await messages(env, token, task["id"]))[0]["attachments"]) == 1


async def test_an_attachment_only_message_is_allowed(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])
    uploaded = await upload(env, token)

    response = await post(
        env, token, task["id"], attachments=[{"fileId": uploaded["fileId"], "kind": "IMAGE"}]
    )

    assert response.status_code == 201
    assert response.json()["text"] == ""


async def test_an_unknown_file_is_refused(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)

    response = await env.post(
        TASKS,
        token,
        body(assignedUserIds=[priya.id], attachments=[{"fileId": "doc_nope", "kind": "IMAGE"}]),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "attachments"


async def test_the_due_date_and_time_survive_a_round_trip(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)

    task = await create_task(env, token, assignedUserIds=[priya.id], dueTime="18:00")

    assert task["dueDate"] == tomorrow()
    assert task["dueTime"] == "18:00"


async def test_a_malformed_due_time_is_refused(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)

    response = await env.post(TASKS, token, body(assignedUserIds=[priya.id], dueTime="6pm"))

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "dueTime"
