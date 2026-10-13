"""Re-uploading after a rejection, and the identifier that may not be used twice.

A rejected customer uploads a fresh scan. Until now both rows sat on the customer with nothing
saying which was current: the review screen listed them side by side, approval marked both
`APPROVED` - including the one the merchant had turned down - and a verification could be done
against either.

The second half is the number itself. `number_lookup_hash` has been written on every document
since encryption landed and was never once read, so the same Aadhaar could open any number of
accounts with the same agency.
"""

import pytest
from sqlalchemy import select

from app.modules.customers.models import CustomerDocument
from tests.integration.customers.conftest import (
    CUSTOMER,
    MERCHANT,
    REG,
    RETAIL_DOCS,
    onboarding,
    registered_customer,
    registration_body,
    reviewer,
    upload_file_id,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def documents_of(env, customer_id: str) -> list[CustomerDocument]:
    async with env.sessions() as db:
        return list(
            await db.scalars(
                select(CustomerDocument)
                .where(CustomerDocument.customer_id == customer_id)
                .order_by(CustomerDocument.submitted_at, CustomerDocument.id)
            )
        )


async def re_upload(env, token, document_type: str, number: str):
    """Upload a fresh scan and PATCH it onto the registration, as the app does."""
    file_id = await upload_file_id(env, CUSTOMER, token, document_type)
    return await env.patch(
        f"{REG}/profile",
        token,
        {"documents": [{"type": document_type, "number": number, "fileId": file_id}]},
    )


# --- The latest upload is the document --------------------------------------------------------


async def test_a_second_upload_supersedes_the_first(env):
    _staff, merchant, _user = await reviewer(env)
    _mobile, token, customer_id = await registered_customer(env, merchant, submit=False)
    before = await documents_of(env, customer_id)
    aadhaar = next(row for row in before if row.document_type == "AADHAAR")

    assert (await re_upload(env, token, "AADHAAR", RETAIL_DOCS["AADHAAR"])).status_code == 200

    after = {row.file_id: row for row in await documents_of(env, customer_id)}
    assert after[aadhaar.file_id].superseded_at is not None
    assert after[aadhaar.file_id].superseded_by_file_id is not None


async def test_the_old_scan_is_kept(env):
    """It is the evidence of what was submitted and when - the point of a document trail."""
    _staff, merchant, _user = await reviewer(env)
    _mobile, token, customer_id = await registered_customer(env, merchant, submit=False)
    before = {row.file_id for row in await documents_of(env, customer_id)}

    await re_upload(env, token, "AADHAAR", RETAIL_DOCS["AADHAAR"])

    after = {row.file_id for row in await documents_of(env, customer_id)}
    assert before <= after


async def test_the_replacement_points_back_at_what_it_replaced(env):
    _staff, merchant, _user = await reviewer(env)
    _mobile, token, customer_id = await registered_customer(env, merchant, submit=False)
    old = next(r for r in await documents_of(env, customer_id) if r.document_type == "AADHAAR")

    await re_upload(env, token, "AADHAAR", RETAIL_DOCS["AADHAAR"])

    rows = await documents_of(env, customer_id)
    new = next(r for r in rows if r.document_type == "AADHAAR" and r.superseded_at is None)
    assert next(r for r in rows if r.file_id == old.file_id).superseded_by_file_id == new.file_id
    assert new.version == (old.version or 1) + 1


async def test_only_the_same_type_is_superseded(env):
    """An Aadhaar does not replace a PAN."""
    _staff, merchant, _user = await reviewer(env)
    _mobile, token, customer_id = await registered_customer(env, merchant, submit=False)
    pan = next(r for r in await documents_of(env, customer_id) if r.document_type == "PAN")

    await re_upload(env, token, "AADHAAR", RETAIL_DOCS["AADHAAR"])

    rows = {r.file_id: r for r in await documents_of(env, customer_id)}
    assert rows[pan.file_id].superseded_at is None


async def test_the_reviewer_sees_one_of_each(env):
    """Two Aadhaars with nothing to tell them apart is what this prevents."""
    staff, merchant, _user = await reviewer(env)
    _mobile, token, customer_id = await registered_customer(env, merchant, submit=False)
    await re_upload(env, token, "AADHAAR", RETAIL_DOCS["AADHAAR"])
    assert (await env.post(f"{REG}/submit", token)).status_code == 200

    detail = await env.get(f"{MERCHANT}/customers/{customer_id}", staff)

    assert detail.status_code == 200, detail.text
    types = [row["type"] for row in detail.json()["documents"]]
    assert len(types) == len(set(types))


async def test_a_replaced_scan_is_not_approved_with_the_rest(env):
    """Approval used to mark every row on the customer, including the one turned down."""
    staff, merchant, _user = await reviewer(env)
    _mobile, token, customer_id = await registered_customer(env, merchant, submit=False)
    old = next(r for r in await documents_of(env, customer_id) if r.document_type == "AADHAAR")
    await re_upload(env, token, "AADHAAR", RETAIL_DOCS["AADHAAR"])
    await env.post(f"{REG}/submit", token)

    approved = await env.post(f"{MERCHANT}/customers/{customer_id}/approve", staff, json={})

    assert approved.status_code == 200, approved.text
    rows = {r.file_id: r for r in await documents_of(env, customer_id)}
    assert rows[old.file_id].status != "APPROVED"
    current = [r for r in rows.values() if r.superseded_at is None]
    assert all(r.status == "APPROVED" for r in current)


async def test_an_approved_customer_can_sign_in_after_re_uploading(env):
    """A replaced scan must not keep them out of their own account."""
    staff, merchant, _user = await reviewer(env)
    mobile, token, customer_id = await registered_customer(env, merchant, submit=False)
    await re_upload(env, token, "AADHAAR", RETAIL_DOCS["AADHAAR"])
    await env.post(f"{REG}/submit", token)
    await env.post(f"{MERCHANT}/customers/{customer_id}/approve", staff, json={})

    login = await env.sign_in("/api/v1/customer/auth", mobile)

    assert login["next_action"] == "OPEN_CUSTOMER_HOME"


async def test_a_replaced_document_still_satisfies_nothing_on_its_own(env):
    """The requirement is met by the replacement, which sits in the same list."""
    _staff, merchant, _user = await reviewer(env)
    _mobile, token, _customer_id = await registered_customer(env, merchant, submit=False)
    await re_upload(env, token, "AADHAAR", RETAIL_DOCS["AADHAAR"])

    submitted = await env.post(f"{REG}/submit", token)

    assert submitted.status_code == 200, submitted.text


# --- One number, one customer -----------------------------------------------------------------


async def test_another_customers_aadhaar_is_refused(env):
    staff, merchant, _user = await reviewer(env)
    _first_mobile, _first_token, _first_id = await registered_customer(
        env, merchant, shared_numbers=True
    )
    taken = next(
        r for r in await documents_of(env, _first_id) if r.document_type == "AADHAAR"
    )
    assert taken.number_lookup_hash

    _mobile, token = await onboarding(env)
    # The same identifiers the first customer registered with - a second person presenting
    # somebody else's Aadhaar, which is the case this refuses.
    body = await registration_body(env, CUSTOMER, token, shared_numbers=True)
    response = await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, **body})

    assert response.status_code == 422, response.text
    codes = {item["code"] for item in response.json()["detail"]["fields"]}
    assert "already_registered" in codes
    assert staff


async def test_the_field_named_is_the_one_on_the_form(env):
    _staff, merchant, _user = await reviewer(env)
    _first_mobile, _first_token, _first_id = await registered_customer(
        env, merchant, shared_numbers=True
    )
    _mobile, token = await onboarding(env)
    body = await registration_body(env, CUSTOMER, token, shared_numbers=True)

    response = await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, **body})

    fields = {item["field"] for item in response.json()["detail"]["fields"]}
    assert any(field.endswith(".number") for field in fields)


async def test_a_customer_may_re_submit_their_own_number(env):
    """Otherwise the copy they are replacing refuses the replacement."""
    _staff, merchant, _user = await reviewer(env)
    _mobile, token, _customer_id = await registered_customer(env, merchant, submit=False)

    again = await re_upload(env, token, "AADHAAR", RETAIL_DOCS["AADHAAR"])

    assert again.status_code == 200, again.text


async def test_the_same_number_at_another_merchant_is_allowed(env):
    """A person can hold a connection with two agencies, and a refusal would tell one of them
    that the number is on file at the other."""
    _staff_a, merchant_a, _user_a = await reviewer(env)
    _staff_b, merchant_b, _user_b = await reviewer(env)
    await registered_customer(env, merchant_a, shared_numbers=True)

    _mobile, token = await onboarding(env)
    body = await registration_body(env, CUSTOMER, token, shared_numbers=True)
    response = await env.post(
        f"{REG}/profile", token, json={"merchant_code": merchant_b.code, **body}
    )

    assert response.status_code == 201, response.text


async def test_a_superseded_number_does_not_block_anybody(env):
    """History must not keep an identifier reserved."""
    _staff, merchant, _user = await reviewer(env)
    _mobile, first_token, first_id = await registered_customer(
        env, merchant, submit=False, shared_numbers=True
    )
    # Replace the first customer's Aadhaar with a different number; the old one is now history.
    await re_upload(env, first_token, "AADHAAR", "999988887777")
    old = next(
        r
        for r in await documents_of(env, first_id)
        if r.document_type == "AADHAAR" and r.superseded_at is not None
    )
    assert old.number_lookup_hash

    _mobile2, token = await onboarding(env)
    body = await registration_body(env, CUSTOMER, token, shared_numbers=True)
    response = await env.post(
        f"{REG}/profile", token, json={"merchant_code": merchant.code, **body}
    )

    # The PAN is still the first customer's and is refused, which is the rule working. What
    # must NOT appear is the Aadhaar: that number is only on a superseded row now, and history
    # does not keep an identifier reserved.
    assert response.status_code == 422, response.text
    fields = {item["field"] for item in response.json()["detail"]["fields"]}
    assert "doc.AADHAAR.number" not in fields
    assert "doc.PAN.number" in fields
