from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.modules.business_catalogue.models import (
    CustomerTypeCylinder,
    CustomerTypeDefinition,
    CustomerTypeKycRule,
    CylinderTypeDefinition,
    KycDocumentTypeDefinition,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]

ADMIN_AUTH = "/api/v1/admin/auth"
MERCHANT_AUTH = "/api/v1/merchant/auth"


async def _admin_token(env) -> str:
    user = await env.create_user(roles=("super_admin",))
    login = await env.sign_in(ADMIN_AUTH, user.mobile_number)
    return login["token"]["access_token"]


async def _manager_token(env) -> str:
    user, _merchant = await env.create_merchant_staff()
    login = await env.sign_in(MERCHANT_AUTH, user.mobile_number)
    return login["token"]["access_token"]


async def test_admin_manages_catalogue_while_manager_has_read_only_access(env):
    suffix = uuid4().hex[:8].upper()
    customer_code = f"TEST_{suffix}"
    cylinder_code = f"CYL_{suffix}"
    document_code = f"DOC_{suffix}"
    admin_token = await _admin_token(env)
    manager_token = await _manager_token(env)

    try:
        customer = await env.post(
            "/api/v1/admin/catalogue/customer-types",
            admin_token,
            {
                "code": customer_code,
                "label": "Test customer class",
                "codePrefix": "TC",
                "requiresDeliverySites": True,
                "requiresGstInvoice": True,
                "sortOrder": 90,
            },
        )
        assert customer.status_code == 201, customer.text

        cylinder = await env.post(
            "/api/v1/admin/catalogue/cylinder-types",
            admin_token,
            {
                "code": cylinder_code,
                "label": "Test 12 KG",
                "weightKg": "12.00",
                "defaultBaseRate": "1000.00",
                "defaultMarkup": "100.00",
                "sortOrder": 90,
            },
        )
        assert cylinder.status_code == 201, cylinder.text
        assert cylinder.json()["defaultUnitPrice"] == "1100.00"

        document = await env.post(
            "/api/v1/admin/catalogue/kyc-document-types",
            admin_token,
            {
                "code": document_code,
                "label": "Test permit",
                "numberPattern": "^[A-Z]{2}[0-9]{4}$",
                "sortOrder": 90,
            },
        )
        assert document.status_code == 201, document.text

        eligibility = await env.client.put(
            f"/api/v1/admin/catalogue/customer-types/{customer_code}/cylinders",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"items": [{"cylinderTypeCode": cylinder_code.lower(), "minQuantity": 2}]},
        )
        assert eligibility.status_code == 200, eligibility.text
        assert eligibility.json()[0]["cylinderTypeCode"] == cylinder_code

        rules = await env.client.put(
            f"/api/v1/admin/catalogue/customer-types/{customer_code}/kyc-rules",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"items": [{"documentTypeCode": document_code.lower(), "requirementMode": "REQUIRED"}]},
        )
        assert rules.status_code == 200, rules.text
        assert rules.json()[0]["documentTypeCode"] == document_code

        visible = await env.get("/api/v1/merchant/catalogue/customer-types", manager_token)
        assert visible.status_code == 200, visible.text
        assert customer_code in {item["code"] for item in visible.json()}

        forbidden = await env.post(
            "/api/v1/merchant/catalogue/customer-types",
            manager_token,
            {"code": f"NO_{suffix}", "label": "Must not be created"},
        )
        assert forbidden.status_code == 403, forbidden.text
    finally:
        await env.execute(delete(CustomerTypeKycRule).where(
            CustomerTypeKycRule.customer_type_code == customer_code
        ))
        await env.execute(delete(CustomerTypeCylinder).where(
            CustomerTypeCylinder.customer_type_code == customer_code
        ))
        await env.execute(delete(KycDocumentTypeDefinition).where(
            KycDocumentTypeDefinition.code == document_code
        ))
        await env.execute(delete(CylinderTypeDefinition).where(
            CylinderTypeDefinition.code == cylinder_code
        ))
        await env.execute(delete(CustomerTypeDefinition).where(
            CustomerTypeDefinition.code == customer_code
        ))
