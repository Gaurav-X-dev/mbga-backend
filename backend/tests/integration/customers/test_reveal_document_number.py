"""Letting a reviewer read the number they are being asked to verify.

Every document number in this project is masked. `mapping.py` is written so that an unmasked
identifier cannot leave through a list or a detail screen, and for an Aadhaar or a PAN that is
the right default.

It also made the review screen impossible to work: a person is asked whether the number on the
form matches the photograph of the card, and `XXXXXXXX9012` cannot be compared with anything.

So there is exactly one way to see the whole value - this route, one document at a time, behind
`customers.verify` on top of the review permissions, and written to the audit log every time.
Nobody reads an identifier without leaving their name on it.
"""

import pytest
from sqlalchemy import select

from app.modules.audit_logs.models import AuditLog
from app.modules.customers.constants import KycDocumentType
from app.modules.customers.models import CustomerDocument
from app.modules.customers.validators import mask_document_number
from tests.integration.customers.conftest import (  # noqa: F401 - fixtures
    MERCHANT,
    env,
    registered_customer,
    reviewer,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]

REVIEWER_RIGHTS = (
    "customers.view",
    "customers.create",
    "customers.approve",
    "customers.reject",
    "customers.review",
    "customer_documents.review",
    "customers.verify",
    "orders.create",
)


async def an_application(env, *, rights: tuple[str, ...] = REVIEWER_RIGHTS):
    staff, merchant, _user = await reviewer(env, permissions=rights)
    _mobile, _token, customer_id = await registered_customer(env, merchant)
    listed = await env.get(f"{MERCHANT}/kyc/applications", staff)
    assert listed.status_code == 200, listed.text
    application = next(
        row for row in listed.json()["items"] if row["customerId"] == customer_id
    )
    return staff, application, customer_id


async def documents_of(env, customer_id: str) -> list[CustomerDocument]:
    async with env.sessions() as db:
        return list(
            await db.scalars(
                select(CustomerDocument).where(CustomerDocument.customer_id == customer_id)
            )
        )


async def reveal(env, token, application_id: str, document_id: str):
    return await env.get(
        f"{MERCHANT}/kyc/applications/{application_id}/documents/{document_id}/number", token
    )


# --- What the reviewer gets ----------------------------------------------------------------------


async def test_the_number_comes_back_in_full(env):
    """Checked by re-masking what came back: it has to mask to the value already on the row,
    which no wrong number could."""
    staff, application, customer_id = await an_application(env)
    aadhaar = next(d for d in await documents_of(env, customer_id) if d.document_type == "AADHAAR")

    response = await reveal(env, staff, application["id"], aadhaar.id)

    assert response.status_code == 200, response.text
    number = response.json()["number"]
    assert mask_document_number(KycDocumentType.AADHAAR, number) == aadhaar.number_masked
    assert len(number) == 12


async def test_the_masked_form_comes_back_too(env):
    """So the screen can go back to hiding it without another call."""
    staff, application, customer_id = await an_application(env)
    aadhaar = next(d for d in await documents_of(env, customer_id) if d.document_type == "AADHAAR")

    body = (await reveal(env, staff, application["id"], aadhaar.id)).json()

    assert body["numberMasked"] == aadhaar.number_masked
    assert body["numberMasked"] != body["number"]


async def test_each_document_is_asked_for_on_its_own(env):
    """Not a screen that opens every identifier the customer has at once."""
    staff, application, customer_id = await an_application(env)
    pan = next(d for d in await documents_of(env, customer_id) if d.document_type == "PAN")

    body = (await reveal(env, staff, application["id"], pan.id)).json()

    assert body["documentType"] == "PAN"
    assert mask_document_number(KycDocumentType.PAN, body["number"]) == pan.number_masked


# --- Everything else stays masked ------------------------------------------------------------------


async def test_the_application_detail_is_still_masked(env):
    """The reveal route exists so that nothing else has to change."""
    staff, application, customer_id = await an_application(env)
    aadhaar = next(d for d in await documents_of(env, customer_id) if d.document_type == "AADHAAR")
    full = (await reveal(env, staff, application["id"], aadhaar.id)).json()["number"]

    detail = await env.get(f"{MERCHANT}/kyc/applications/{application['id']}", staff)

    assert detail.status_code == 200, detail.text
    assert full not in detail.text


async def test_the_queue_is_still_masked(env):
    staff, application, customer_id = await an_application(env)
    aadhaar = next(d for d in await documents_of(env, customer_id) if d.document_type == "AADHAAR")
    full = (await reveal(env, staff, application["id"], aadhaar.id)).json()["number"]

    listed = await env.get(f"{MERCHANT}/kyc/applications", staff)

    assert full not in listed.text


# --- Who may look, and what that leaves behind -------------------------------------------------------


async def test_every_reveal_is_written_to_the_audit_log(env):
    staff, application, customer_id = await an_application(env)
    aadhaar = next(d for d in await documents_of(env, customer_id) if d.document_type == "AADHAAR")

    await reveal(env, staff, application["id"], aadhaar.id)

    async with env.sessions() as db:
        entry = await db.scalar(
            select(AuditLog).where(
                AuditLog.event_type == "customer_document.number_revealed",
                AuditLog.entity_id == aadhaar.id,
            )
        )
    assert entry is not None
    assert entry.actor_user_id


async def test_the_audit_line_carries_no_number(env):
    """An audit log that quotes the identifier defeats the masking it is recording."""
    staff, application, customer_id = await an_application(env)
    aadhaar = next(d for d in await documents_of(env, customer_id) if d.document_type == "AADHAAR")

    await reveal(env, staff, application["id"], aadhaar.id)

    async with env.sessions() as db:
        entry = await db.scalar(
            select(AuditLog).where(AuditLog.entity_id == aadhaar.id)
        )
    full = (await reveal(env, staff, application["id"], aadhaar.id)).json()["number"]
    assert full not in (entry.message or "")


async def test_a_reviewer_without_verify_may_not_look(env):
    """Reading the queue is not the same right as reading an Aadhaar."""
    rights = tuple(r for r in REVIEWER_RIGHTS if r != "customers.verify")
    staff, application, customer_id = await an_application(env, rights=rights)
    aadhaar = next(d for d in await documents_of(env, customer_id) if d.document_type == "AADHAAR")

    response = await reveal(env, staff, application["id"], aadhaar.id)

    assert response.status_code == 403, response.text


async def test_another_merchants_application_is_not_found(env):
    staff, _application, _customer = await an_application(env)
    _other_staff, theirs, their_customer = await an_application(env)
    document = next(d for d in await documents_of(env, their_customer))

    response = await reveal(env, staff, theirs["id"], document.id)

    assert response.status_code == 404, response.text


async def test_a_document_from_another_application_is_not_found(env):
    """The document id alone is not a key: it has to belong to the application being reviewed."""
    staff, application, _customer_id = await an_application(env)
    _other, _theirs, their_customer = await an_application(env)
    foreign = next(d for d in await documents_of(env, their_customer))

    response = await reveal(env, staff, application["id"], foreign.id)

    assert response.status_code == 404, response.text


async def test_the_detail_carries_the_id_the_reveal_route_needs(env):
    """Without it a reviewer's screen has a masked number and no way to ask for the rest.

    The reveal route is addressed by document id, and the application detail - the only screen
    that lists the documents - did not carry one. The button had nothing to send.
    """
    staff, application, customer_id = await an_application(env)
    stored = {d.id for d in await documents_of(env, customer_id)}

    detail = await env.get(f"{MERCHANT}/kyc/applications/{application['id']}", staff)

    assert detail.status_code == 200, detail.text
    listed = {row["id"] for row in detail.json()["documents"]}
    assert listed == stored


async def test_the_id_from_the_detail_opens_the_number(env):
    """The two halves joined up: what the screen is given is what the route accepts."""
    staff, application, _customer_id = await an_application(env)
    detail = await env.get(f"{MERCHANT}/kyc/applications/{application['id']}", staff)
    row = next(d for d in detail.json()["documents"] if d["type"] == "AADHAAR")

    response = await reveal(env, staff, application["id"], row["id"])

    assert response.status_code == 200, response.text
    assert response.json()["numberMasked"] == row["numberMasked"]
