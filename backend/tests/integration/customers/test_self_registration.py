"""Customer self-registration against the full API_SPEC contract."""

import pytest

from tests.integration.authentication.conftest import code_of
from tests.integration.customers.conftest import (
    ADDRESS,
    CUSTOMER,
    REG,
    onboarding,
    registration_body,
    reviewer,
    site,
    upload_file_id,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


def fields_of(response) -> dict[str, str]:
    return {item["field"]: item["code"] for item in response.json()["detail"]["fields"]}


async def test_retail_registration_and_submission(env):
    _, merchant, _ = await reviewer(env)
    _, token = await onboarding(env)
    body = await registration_body(env, CUSTOMER, token)

    created = await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, **body})
    assert created.status_code == 201, created.text

    submitted = await env.post(f"{REG}/submit", token)
    assert submitted.status_code == 200, submitted.text
    progress = submitted.json()["progress"]
    assert progress["accountStatus"] == "PENDING"
    assert progress["kycStatus"] == "PENDING"
    assert progress["applicationStatus"] == "PENDING"
    assert progress["profileComplete"] is True
    assert progress["missingFields"] == []
    # Spec 3.6: retail codes are MBGA-R-nnnn.
    assert progress["code"].startswith("MBGA-R-")


async def test_industrial_registration_stores_gstin_and_a_primary_site(env):
    _, merchant, _ = await reviewer(env)
    _, token = await onboarding(env)
    body = await registration_body(env, CUSTOMER, token, customer_type="INDUSTRIAL")
    body["sites"] = [site("Plant A"), site("Plant B", primary=False)]

    created = await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, **body})
    assert created.status_code == 201, created.text
    submitted = await env.post(f"{REG}/submit", token)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["progress"]["code"].startswith("MBGA-I-")


@pytest.mark.parametrize(
    ("override", "expected_field"),
    [
        ({"businessName": ""}, "businessName"),
        ({"ownerName": " "}, "ownerName"),
        ({"email": "not-an-email"}, "email"),
        ({"deliveryAddress": {**ADDRESS, "line1": ""}}, "deliveryAddress.line1"),
        ({"deliveryAddress": {**ADDRESS, "city": ""}}, "deliveryAddress.city"),
        ({"deliveryAddress": {**ADDRESS, "pincode": "45200"}}, "deliveryAddress.pincode"),
        ({"deliveryAddress": {**ADDRESS, "state": ""}}, "deliveryAddress.state"),
    ],
)
async def test_invalid_business_fields_are_reported_by_name(env, override, expected_field):
    _, merchant, _ = await reviewer(env)
    _, token = await onboarding(env)
    body = await registration_body(env, CUSTOMER, token)

    response = await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, **body, **override})
    assert response.status_code == 422, response.text
    assert expected_field in fields_of(response)


async def test_every_invalid_field_is_reported_at_once(env):
    """A long form must not be fixed one error per round trip."""
    _, merchant, _ = await reviewer(env)
    _, token = await onboarding(env)
    body = await registration_body(env, CUSTOMER, token)
    body |= {"businessName": "", "ownerName": "", "email": "bad", "deliveryAddress": {**ADDRESS, "pincode": "x"}}

    response = await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, **body})
    reported = fields_of(response)
    assert {"businessName", "ownerName", "email", "deliveryAddress.pincode"} <= set(reported)


@pytest.mark.parametrize(
    ("customer_type", "document_type", "bad_number"),
    [
        ("RETAIL", "AADHAAR", "12341234123"),
        ("RETAIL", "PAN", "ABCD1234F"),
        ("INDUSTRIAL", "FSSAI", "1234567890123"),
        ("INDUSTRIAL", "GST", "23AAACA1234F1ZZ5"),
    ],
)
async def test_invalid_document_numbers_are_refused(env, customer_type, document_type, bad_number):
    _, merchant, _ = await reviewer(env)
    _, token = await onboarding(env)
    body = await registration_body(env, CUSTOMER, token, customer_type=customer_type)
    for document in body["documents"]:
        if document["type"] == document_type:
            document["number"] = bad_number

    response = await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, **body})
    assert response.status_code == 422, response.text
    assert f"doc.{document_type}.number" in fields_of(response)


async def test_a_customer_cannot_attach_another_customers_upload(env):
    _, merchant, _ = await reviewer(env)
    _, mine = await onboarding(env)
    _, theirs = await onboarding(env)
    stolen = await upload_file_id(env, CUSTOMER, theirs, "AADHAAR")

    body = await registration_body(env, CUSTOMER, mine)
    for document in body["documents"]:
        if document["type"] == "AADHAAR":
            document["fileName"] = stolen

    response = await env.post(f"{REG}/profile", mine, json={"merchant_code": merchant.code, **body})
    assert response.status_code == 422, response.text
    # Reported exactly as a missing file would be, so the response cannot confirm the id.
    assert fields_of(response)["doc.AADHAAR.file"] == "not_found"


async def test_an_upload_cannot_be_used_twice(env):
    _, merchant, _ = await reviewer(env)
    _, first = await onboarding(env)
    body = await registration_body(env, CUSTOMER, first)
    created = await env.post(f"{REG}/profile", first, json={"merchant_code": merchant.code, **body})
    assert created.status_code == 201, created.text

    _, second = await onboarding(env)
    reused = await registration_body(env, CUSTOMER, second)
    reused["documents"] = body["documents"]
    response = await env.post(f"{REG}/profile", second, json={"merchant_code": merchant.code, **reused})
    assert response.status_code == 422, response.text
    assert set(fields_of(response).values()) <= {"not_found", "already_used"}


async def test_a_file_cannot_be_submitted_as_a_different_document_type(env):
    _, merchant, _ = await reviewer(env)
    _, token = await onboarding(env)
    pan_file = await upload_file_id(env, CUSTOMER, token, "PAN")
    body = await registration_body(env, CUSTOMER, token)
    for document in body["documents"]:
        if document["type"] == "AADHAAR":
            document["fileName"] = pan_file

    response = await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, **body})
    assert response.status_code == 422, response.text
    assert fields_of(response)["doc.AADHAAR.file"] == "type_mismatch"


async def test_retail_customers_cannot_submit_industrial_data(env):
    _, merchant, _ = await reviewer(env)
    _, token = await onboarding(env)
    body = await registration_body(env, CUSTOMER, token)
    body["sites"] = [site()]

    response = await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, **body})
    assert response.status_code == 422, response.text
    assert fields_of(response)["sites"] == "not_applicable"


async def test_industrial_registration_needs_exactly_one_primary_site(env):
    _, merchant, _ = await reviewer(env)
    _, token = await onboarding(env)
    body = await registration_body(env, CUSTOMER, token, customer_type="INDUSTRIAL")
    body["sites"] = [site("Plant A"), site("Plant B")]

    response = await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, **body})
    assert response.status_code == 422, response.text
    assert fields_of(response)["sites"] == "multiple_primary"


async def test_industrial_registration_needs_at_least_one_site(env):
    _, merchant, _ = await reviewer(env)
    _, token = await onboarding(env)
    body = await registration_body(env, CUSTOMER, token, customer_type="INDUSTRIAL")
    body["sites"] = []

    response = await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, **body})
    assert response.status_code == 422, response.text
    assert fields_of(response)["sites"] == "required"


async def test_duplicate_sites_in_one_request_are_refused(env):
    _, merchant, _ = await reviewer(env)
    _, token = await onboarding(env)
    body = await registration_body(env, CUSTOMER, token, customer_type="INDUSTRIAL")
    body["sites"] = [site("Plant A"), site("Plant A", primary=False)]

    response = await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, **body})
    assert response.status_code == 422, response.text
    assert fields_of(response)["sites.1.name"] == "duplicate"


async def test_a_customer_cannot_register_a_number_they_did_not_verify(env):
    _, merchant, _ = await reviewer(env)
    mobile, token = await onboarding(env)
    body = await registration_body(env, CUSTOMER, token, mobile="9000000099")

    response = await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, **body})
    assert (response.status_code, code_of(response)) == (403, "PERMISSION_DENIED")

    # The verified number itself is accepted.
    body["mobile"] = mobile.removeprefix("+91")
    assert (await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, **body})).status_code == 201


async def test_submitting_an_incomplete_registration_lists_what_is_missing(env):
    _, merchant, _ = await reviewer(env)
    _, token = await onboarding(env)
    aadhaar = await upload_file_id(env, CUSTOMER, token, "AADHAAR")
    partial = {
        "merchant_code": merchant.code,
        "customerType": "RETAIL",
        "businessName": "Half Filled",
        "ownerName": "Ravi Kumar",
        "deliveryAddress": dict(ADDRESS),
        "documents": [{"type": "AADHAAR", "number": "123412341234", "fileName": aadhaar}],
    }
    created = await env.post(f"{REG}/profile", token, json=partial)
    assert created.status_code == 201, created.text

    response = await env.post(f"{REG}/submit", token)
    assert (response.status_code, code_of(response)) == (422, "REGISTRATION_INCOMPLETE")
    assert "doc.PAN" in fields_of(response)

    status_response = await env.get(f"{REG}/status", token)
    progress = status_response.json()["progress"]
    assert progress["missingDocumentTypes"] == ["PAN"]
    assert progress["profileComplete"] is False


async def test_submitting_twice_does_not_open_a_second_application(env):
    _, merchant, _ = await reviewer(env)
    _, token = await onboarding(env)
    body = await registration_body(env, CUSTOMER, token)
    await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, **body})

    first = await env.post(f"{REG}/submit", token)
    second = await env.post(f"{REG}/submit", token)
    assert first.status_code == second.status_code == 200, second.text
    assert first.json()["progress"]["applicationId"] == second.json()["progress"]["applicationId"]


async def test_a_submitted_registration_can_no_longer_be_edited(env):
    _, merchant, _ = await reviewer(env)
    _, token = await onboarding(env)
    body = await registration_body(env, CUSTOMER, token)
    await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, **body})
    await env.post(f"{REG}/submit", token)

    response = await env.client.patch(
        f"{REG}/profile",
        json={"businessName": "Renamed Mid-Review"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert (response.status_code, code_of(response)) == (409, "REGISTRATION_NOT_EDITABLE")


async def test_status_before_registration_reports_nothing_started(env):
    _, token = await onboarding(env)
    response = await env.get(f"{REG}/status", token)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "NOT_STARTED"
    assert response.json()["progress"] is None
