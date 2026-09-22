"""Shared fixtures for the customer registration and KYC slice.

Reuses the authentication suite's database, migration and environment fixtures rather than
rebuilding them - there is one migration/seed path for the whole integration suite. That
conftest is only imported here, never edited.
"""

from uuid import uuid4

import pytest

# Imported so pytest collects them as fixtures in this package.
from tests.integration.authentication.conftest import (  # noqa: F401
    AuthEnv,
    _prepared_database,
    code_of,
    database_url,
    env,
    random_mobile,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


@pytest.fixture
def settings_overrides(request) -> dict:
    overrides = {"allow_skipped_kyc_scan_in_local": True}
    overrides.update(getattr(request, "param", {}) or {})
    return overrides

REG = "/api/v1/customer/registration"
CUSTOMER = "/api/v1/customer"
MERCHANT = "/api/v1/merchant"
MERCHANT_AUTH = "/api/v1/merchant/auth"

# Smallest valid files of each accepted type. Real bytes, so the signature check is exercised
# rather than mocked.
PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\x00IEND\xaeB`\x82"
)

RETAIL_DOCS = {"AADHAAR": "123412341234", "PAN": "ABCDE1234F"}
INDUSTRIAL_DOCS = {"FSSAI": "12345678901234", "GST": "23AAACA1234F1Z5"}

ADDRESS = {
    "line1": "12 MG Road",
    "line2": "Near the bus stand",
    "city": "Indore",
    "state": "Madhya Pradesh",
    "pincode": "452001",
}


def site(name: str = "Plant A", *, pincode: str = "452001", primary: bool = True) -> dict:
    return {
        "name": name,
        "address": {**ADDRESS, "line1": f"Plot 22, {name}", "pincode": pincode},
        "contactName": "Ramesh Patil",
        "contactMobile": "9822001122",
        "isPrimary": primary,
    }


async def upload(auth_env, prefix: str, token: str, document_type: str, *, content: bytes = PDF_BYTES, filename: str = "scan.pdf", content_type: str = "application/pdf"):
    """Upload one document and return the response."""
    return await auth_env.client.post(
        f"{prefix}/documents",
        files={"file": (filename, content, content_type)},
        data={"type": document_type},
        headers={"Authorization": f"Bearer {token}"},
    )


async def upload_file_id(auth_env, prefix: str, token: str, document_type: str, **kwargs) -> str:
    response = await upload(auth_env, prefix, token, document_type, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()["fileId"]


async def registration_body(auth_env, prefix: str, token: str, *, customer_type: str = "RETAIL", mobile: str | None = None, **overrides) -> dict:
    """A complete registration payload with freshly uploaded documents."""
    numbers = RETAIL_DOCS if customer_type == "RETAIL" else INDUSTRIAL_DOCS
    documents = [
        {"type": kind, "number": number, "fileName": await upload_file_id(auth_env, prefix, token, kind)}
        for kind, number in numbers.items()
    ]
    body = {
        "customerType": customer_type,
        "businessName": "Test Bakery",
        "ownerName": "Ravi Kumar",
        "email": "ravi@testbakery.in",
        "deliveryAddress": dict(ADDRESS),
        "documents": documents,
    }
    if customer_type == "INDUSTRIAL":
        body["sites"] = [site()]
    if mobile:
        body["mobile"] = mobile
    body.update(overrides)
    return body


async def reviewer(auth_env, merchant=None, permissions: tuple[str, ...] = ("customers.view", "customers.create", "customers.approve", "customers.reject", "customers.review", "customer_documents.review", "orders.create")):
    """Merchant staff with the full set of customer and KYC permissions."""
    role = f"kyc_reviewer_{uuid4().hex[:8]}"
    await auth_env.create_role(role, "MERCHANT", list(permissions))
    user, merchant = await auth_env.create_merchant_staff(merchant, roles=("manager", role))
    login = await auth_env.sign_in(MERCHANT_AUTH, user.mobile_number)
    return login["token"]["access_token"], merchant, user


async def onboarding(auth_env, mobile: str | None = None) -> tuple[str, str]:
    """Start a customer onboarding session. Returns the mobile and its access token."""
    mobile = mobile or random_mobile()
    session = await auth_env.sign_in(REG, mobile)
    return mobile, session["token"]["access_token"]


async def registered_customer(auth_env, merchant, *, customer_type: str = "RETAIL", submit: bool = True) -> tuple[str, str, str]:
    """A self-registered customer. Returns mobile, onboarding token and customer id."""
    mobile, token = await onboarding(auth_env)
    body = await registration_body(auth_env, CUSTOMER, token, customer_type=customer_type)
    created = await auth_env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, **body})
    assert created.status_code == 201, created.text
    if submit:
        submitted = await auth_env.post(f"{REG}/submit", token)
        assert submitted.status_code == 200, submitted.text
    return mobile, token, created.json()["id"]
