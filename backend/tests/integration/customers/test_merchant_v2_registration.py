"""Merchant V2 creates customers with two-image KYC without changing V1 responses."""

import pytest
from sqlalchemy import select

from app.modules.customers.v2_models import CustomerDocumentFileV2
from tests.integration.authentication.conftest import random_mobile
from tests.integration.customers.conftest import ADDRESS, JPEG_BYTES, reviewer

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

V1_MERCHANT = "/api/v1/merchant"
V2_MERCHANT = "/api/v2/merchant"


async def _upload(env, token: str, side: str) -> str:
    response = await env.client.post(
        f"{V2_MERCHANT}/documents",
        files={"file": (f"aadhaar-{side.lower()}.jpg", JPEG_BYTES, "image/jpeg")},
        data={"type": "AADHAAR", "side": side, "source": "CAMERA"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["side"] == side
    return response.json()["fileId"]


async def test_merchant_v2_creates_customer_with_front_and_back_images(env) -> None:
    token, _merchant, _staff = await reviewer(env)
    front = await _upload(env, token, "FRONT")
    back = await _upload(env, token, "BACK")
    response = await env.post(
        f"{V2_MERCHANT}/customers",
        token,
        json={
            "customerType": "RETAIL",
            "businessName": "Merchant V2 Bakery",
            "ownerName": "Ravi Kumar",
            "mobile": random_mobile().removeprefix("+91"),
            "deliveryAddress": ADDRESS,
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
        },
    )
    assert response.status_code == 201, response.text
    customer = response.json()
    files = customer["documents"][0]["files"]
    assert [(item["fileId"], item["side"]) for item in files] == [
        (front, "FRONT"),
        (back, "BACK"),
    ]

    async with env.sessions() as session:
        mappings = list(
            await session.scalars(
                select(CustomerDocumentFileV2)
                .where(
                    CustomerDocumentFileV2.customer_id == customer["id"],
                    CustomerDocumentFileV2.superseded_at.is_(None),
                )
                .order_by(CustomerDocumentFileV2.sort_order)
            )
        )
        assert [(row.file_id, row.side) for row in mappings] == [
            (front, "FRONT"),
            (back, "BACK"),
        ]

    v1_detail = await env.get(f"{V1_MERCHANT}/customers/{customer['id']}", token)
    assert v1_detail.status_code == 200, v1_detail.text
    assert v1_detail.json()["documents"][0]["fileId"] == front
    assert "files" not in v1_detail.json()["documents"][0]
