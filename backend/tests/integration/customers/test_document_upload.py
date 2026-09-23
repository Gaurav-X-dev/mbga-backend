"""Document upload, ownership and secure viewing."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.modules.customers.cleanup import OrphanedUploadCleanupService
from app.modules.customers.dependencies import get_storage
from app.modules.customers.models import CustomerDocument
from tests.integration.authentication.conftest import code_of
from tests.integration.customers.conftest import (
    CUSTOMER,
    JPEG_BYTES,
    MERCHANT,
    PDF_BYTES,
    PNG_BYTES,
    onboarding,
    registered_customer,
    reviewer,
    upload,
    upload_file_id,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


@pytest.mark.parametrize(
    ("content", "filename", "declared", "expected_type"),
    [
        (PDF_BYTES, "aadhaar.pdf", "application/pdf", "application/pdf"),
        (JPEG_BYTES, "aadhaar.jpg", "image/jpeg", "image/jpeg"),
        (PNG_BYTES, "aadhaar.png", "image/png", "image/png"),
    ],
)
async def test_each_accepted_format_uploads(env, content, filename, declared, expected_type):
    _, token = await onboarding(env)
    response = await upload(env, CUSTOMER, token, "AADHAAR", content=content, filename=filename, content_type=declared)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["contentType"] == expected_type
    assert body["size"] == len(content)
    assert body["fileId"].startswith("doc_")
    # The physical location must never reach the client.
    assert "storage" not in response.text.lower()
    assert "kyc/" not in response.text


async def test_the_bytes_decide_the_type_not_the_headers(env):
    """A PNG renamed to .pdf and declared as a PDF is refused, not believed."""
    _, token = await onboarding(env)
    response = await upload(env, CUSTOMER, token, "PAN", content=PNG_BYTES, filename="pan.pdf", content_type="application/pdf")
    assert (response.status_code, code_of(response)) == (415, "FILE_TYPE_MISMATCH")


@pytest.mark.parametrize(
    ("content", "label"),
    [
        (b"MZ\x90\x00\x03\x00\x00\x00", "windows executable"),
        (b"\x7fELF\x02\x01\x01\x00", "linux executable"),
        (b"PK\x03\x04\x14\x00\x00\x00", "zip archive"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>', "svg"),
        (b"#!/bin/sh\nrm -rf /\n", "shell script"),
    ],
)
async def test_dangerous_formats_are_refused(env, content, label):
    _, token = await onboarding(env)
    response = await upload(env, CUSTOMER, token, "AADHAAR", content=content, filename="doc.pdf")
    assert response.status_code == 415, f"{label} was accepted: {response.text}"


async def test_an_oversized_file_is_cut_off_during_the_stream(env):
    """The limit is enforced as the bytes arrive, not after buffering the whole upload."""
    _, token = await onboarding(env)
    oversized = PDF_BYTES + b"\x00" * (6 * 1024 * 1024)
    response = await upload(env, CUSTOMER, token, "AADHAAR", content=oversized)
    assert (response.status_code, code_of(response)) == (413, "FILE_TOO_LARGE")


async def test_a_traversal_filename_never_becomes_a_path(env):
    _, token = await onboarding(env)
    response = await upload(env, CUSTOMER, token, "PAN", filename="../../../etc/passwd.pdf")
    assert response.status_code == 201, response.text
    # The name is kept only for display, with every path component stripped.
    assert response.json()["fileName"] == "passwd.pdf"


async def test_a_customer_cannot_read_another_customers_upload(env):
    _, first = await onboarding(env)
    _, second = await onboarding(env)
    file_id = await upload_file_id(env, CUSTOMER, first, "AADHAAR")

    own = await env.get(f"{CUSTOMER}/documents/{file_id}/url", first)
    assert own.status_code == 200, own.text
    foreign = await env.get(f"{CUSTOMER}/documents/{file_id}/url", second)
    # 404, not 403: a 403 would confirm the file id is real.
    assert (foreign.status_code, code_of(foreign)) == (404, "DOCUMENT_NOT_FOUND")


async def test_a_merchant_cannot_read_another_merchants_upload(env):
    first_token, _, _ = await reviewer(env)
    second_token, _, _ = await reviewer(env)
    file_id = await upload_file_id(env, MERCHANT, first_token, "PAN")

    assert (await env.get(f"{MERCHANT}/documents/{file_id}/url", first_token)).status_code == 200
    foreign = await env.get(f"{MERCHANT}/documents/{file_id}/url", second_token)
    assert (foreign.status_code, code_of(foreign)) == (404, "DOCUMENT_NOT_FOUND")


async def test_the_view_url_is_short_lived_and_not_cacheable(env):
    _, token = await onboarding(env)
    file_id = await upload_file_id(env, CUSTOMER, token, "AADHAAR")

    response = await env.get(f"{CUSTOMER}/documents/{file_id}/url", token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["expiresInSeconds"] == 300
    assert response.headers["cache-control"] == "no-store"
    assert "token=" in body["url"]
    # Absolute, so the app can hand it straight to an image view. A relative path would
    # resolve against the app bundle rather than the API.
    assert body["url"].startswith("http")
    assert "/api/v1/customer/documents/" in body["url"]


async def test_the_signed_link_opens_with_no_authorization_header(env):
    """Spec 17.2: the app hands this straight to an image view, which sends no headers."""
    _, first = await onboarding(env)
    file_id = await upload_file_id(env, CUSTOMER, first, "AADHAAR")
    url = (await env.get(f"{CUSTOMER}/documents/{file_id}/url", first)).json()["url"]

    served = await env.get(url)  # deliberately no token argument
    assert served.status_code == 200, served.text
    assert served.content == PDF_BYTES
    assert served.headers["cache-control"] == "no-store"
    assert served.headers["x-content-type-options"] == "nosniff"


async def test_a_link_signed_for_one_file_cannot_serve_another(env):
    _, token = await onboarding(env)
    first = await upload_file_id(env, CUSTOMER, token, "AADHAAR")
    second = await upload_file_id(env, CUSTOMER, token, "PAN")
    signed = (await env.get(f"{CUSTOMER}/documents/{first}/url", token)).json()["url"].split("token=")[1]

    swapped = await env.get(f"{CUSTOMER}/documents/{second}/content?token={signed}")
    assert swapped.status_code == 404


async def test_a_tampered_token_is_refused(env):
    """The signature is what authorises the fetch, so forging it must fail."""
    _, token = await onboarding(env)
    file_id = await upload_file_id(env, CUSTOMER, token, "AADHAAR")
    signed = (await env.get(f"{CUSTOMER}/documents/{file_id}/url", token)).json()["url"].split("token=")[1]

    garbled = await env.get(f"{CUSTOMER}/documents/{file_id}/content?token={signed[:-4]}zzzz")
    assert garbled.status_code == 404
    missing = await env.get(f"{CUSTOMER}/documents/{file_id}/content?token=")
    assert missing.status_code in {404, 422}


async def test_a_reviewer_without_the_document_permission_cannot_open_documents(env):
    full_token, merchant, _ = await reviewer(env)
    file_id = await upload_file_id(env, MERCHANT, full_token, "PAN")
    limited_token, _, _ = await reviewer(env, merchant, permissions=("customers.view", "customers.review"))

    denied = await env.get(f"{MERCHANT}/documents/{file_id}/url", limited_token)
    assert (denied.status_code, code_of(denied)) == (403, "PERMISSION_DENIED")


async def test_the_document_number_is_never_present_on_an_upload_response(env):
    _, token = await onboarding(env)
    response = await upload(env, CUSTOMER, token, "AADHAAR")
    assert "123412341234" not in response.text
    assert set(response.json()) == {"fileId", "fileName", "contentType", "size"}


async def test_orphan_cleanup_deletes_only_expired_unfinalized_uploads(env):
    _, merchant, _ = await reviewer(env)
    _, onboarding_token, customer_id = await registered_customer(env, merchant)
    abandoned_file_id = await upload_file_id(env, CUSTOMER, onboarding_token, "AADHAAR")
    old = datetime.now(UTC) - timedelta(hours=48)
    async with env.sessions() as db:
        abandoned = await db.scalar(select(CustomerDocument).where(CustomerDocument.file_id == abandoned_file_id))
        finalized = await db.scalar(
            select(CustomerDocument).where(
                CustomerDocument.customer_id == customer_id,
                CustomerDocument.finalized_at.is_not(None),
            )
        )
        abandoned.created_at = old
        finalized.created_at = old
        await db.commit()

    async with env.sessions() as db:
        result = await OrphanedUploadCleanupService(db, get_storage(env.settings)).cleanup(
            retention_hours=24,
            dry_run=False,
            now=datetime.now(UTC),
        )
        await db.commit()

    assert result.file_ids == [abandoned_file_id]
    async with env.sessions() as db:
        assert await db.scalar(select(CustomerDocument).where(CustomerDocument.file_id == abandoned_file_id)) is None
        assert await db.scalar(select(CustomerDocument).where(CustomerDocument.customer_id == customer_id)) is not None
