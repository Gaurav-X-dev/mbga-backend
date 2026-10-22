"""V2 KYC images are grouped separately while V1 sees only the primary image."""

import pytest
from sqlalchemy import select

from app.modules.customers.models import CustomerDocument, KycApplication
from app.modules.customers.v2_models import CustomerDocumentFileV2
from tests.integration.customers.conftest import ADDRESS, JPEG_BYTES, onboarding, reviewer

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

V1_REG = "/api/v1/customer/registration"
V2_CUSTOMER = "/api/v2/customer"
V2_REG = f"{V2_CUSTOMER}/registration"


async def _upload(env, token: str, side: str) -> str:
    response = await env.client.post(
        f"{V2_CUSTOMER}/documents",
        files={"file": (f"aadhaar-{side.lower()}.jpg", JPEG_BYTES, "image/jpeg")},
        data={"type": "AADHAAR", "side": side, "source": "CAMERA"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["side"] == side
    assert response.json()["source"] == "CAMERA"
    return response.json()["fileId"]


async def test_two_images_are_v2_mapped_but_only_primary_is_linked_to_v1(env) -> None:
    merchant_token, merchant, _ = await reviewer(env)
    _, token = await onboarding(env)
    front = await _upload(env, token, "FRONT")
    back = await _upload(env, token, "BACK")
    payload = {
        "merchant_code": merchant.code,
        "customer_type": "RETAIL",
        "business_name": "Two Image Bakery",
        "owner_name": "Ravi Kumar",
        "delivery_address": ADDRESS,
        "documents": [
            {
                "type": "AADHAAR",
                "number": "123412341234",
                "files": [
                    {"fileId": front, "side": "FRONT", "source": "CAMERA"},
                    {"fileId": back, "side": "BACK", "source": "CAMERA"},
                ],
            }
        ],
    }
    created = await env.post(f"{V2_REG}/profile", token, json=payload)
    assert created.status_code == 201, created.text
    customer_id = created.json()["id"]

    async with env.sessions() as session:
        mappings = list(
            await session.scalars(
                select(CustomerDocumentFileV2)
                .where(
                    CustomerDocumentFileV2.customer_id == customer_id,
                    CustomerDocumentFileV2.superseded_at.is_(None),
                )
                .order_by(CustomerDocumentFileV2.sort_order)
            )
        )
        assert [(row.file_id, row.side) for row in mappings] == [(front, "FRONT"), (back, "BACK")]
        documents = list(
            await session.scalars(
                select(CustomerDocument).where(CustomerDocument.file_id.in_([front, back]))
            )
        )
        by_file = {row.file_id: row for row in documents}
        assert by_file[front].customer_id == customer_id
        assert by_file[back].customer_id is None
        assert by_file[back].finalized_at is not None

    # The live V1 profile contract still reads the same shared profile successfully.
    v1_profile = await env.get(f"{V1_REG}/profile", token)
    assert v1_profile.status_code == 200, v1_profile.text
    assert set(v1_profile.json()) == set(created.json())
    submitted = await env.post(f"{V2_REG}/submit", token)
    assert submitted.status_code == 200, submitted.text

    async with env.sessions() as session:
        application = await session.scalar(
            select(KycApplication).where(KycApplication.customer_id == customer_id)
        )
        assert application is not None
        application_id = application.id

    merchant_detail = await env.get(
        f"/api/v2/merchant/kyc/applications/{application_id}", merchant_token
    )
    assert merchant_detail.status_code == 200, merchant_detail.text
    files = merchant_detail.json()["documents"][0]["files"]
    assert [(item["fileId"], item["side"]) for item in files] == [
        (front, "FRONT"),
        (back, "BACK"),
    ]

    back_url = await env.get(f"/api/v2/merchant/documents/{back}/url", merchant_token)
    assert back_url.status_code == 200, back_url.text
    served = await env.get(back_url.json()["url"])
    assert served.status_code == 200
    assert served.content == JPEG_BYTES

    approved = await env.post(
        f"/api/v2/merchant/kyc/applications/{application_id}/approve", merchant_token
    )
    assert approved.status_code == 200, approved.text


async def test_duplicate_sides_are_rejected(env) -> None:
    _, merchant, _ = await reviewer(env)
    _, token = await onboarding(env)
    first = await _upload(env, token, "FRONT")
    second = await _upload(env, token, "FRONT")
    response = await env.post(
        f"{V2_REG}/profile",
        token,
        json={
            "merchant_code": merchant.code,
            "customer_type": "RETAIL",
            "business_name": "Duplicate Side Bakery",
            "owner_name": "Ravi Kumar",
            "delivery_address": ADDRESS,
            "documents": [
                {
                    "type": "AADHAAR",
                    "number": "123412341234",
                    "files": [
                        {"fileId": first, "side": "FRONT"},
                        {"fileId": second, "side": "FRONT"},
                    ],
                }
            ],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
