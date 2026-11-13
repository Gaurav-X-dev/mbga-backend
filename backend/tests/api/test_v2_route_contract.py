from app.main import app


def test_v1_upload_response_contract_is_unchanged() -> None:
    paths = app.openapi()["paths"]
    operation = paths["/api/v1/customer/documents"]["post"]
    schema = operation["responses"]["201"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/DocumentUploadResponse"}

    merchant_upload = paths["/api/v1/merchant/documents"]["post"]
    merchant_upload_schema = merchant_upload["responses"]["201"]["content"][
        "application/json"
    ]["schema"]
    assert merchant_upload_schema == {
        "$ref": "#/components/schemas/DocumentUploadResponse"
    }

    merchant_create = paths["/api/v1/merchant/customers"]["post"]
    merchant_create_schema = merchant_create["responses"]["201"]["content"][
        "application/json"
    ]["schema"]
    assert merchant_create_schema == {"$ref": "#/components/schemas/CustomerResponse"}


def test_v2_registration_and_upload_routes_are_separate() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v2/customer/documents" in paths
    assert "/api/v2/customer/registration/kyc-requirements" in paths
    assert "/api/v2/customer/registration/profile" in paths
    assert "/api/v2/customer/registration/submit" in paths
    upload_schema = paths["/api/v2/customer/documents"]["post"]["responses"]["201"][
        "content"
    ]["application/json"]["schema"]
    assert upload_schema == {"$ref": "#/components/schemas/DocumentUploadResponseV2"}


def test_merchant_v2_review_routes_are_separate() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v2/merchant/customers",
        "/api/v2/merchant/documents",
        "/api/v2/merchant/kyc/applications",
        "/api/v2/merchant/kyc/applications/{application_id}",
        "/api/v2/merchant/kyc/applications/{application_id}/approve",
        "/api/v2/merchant/kyc/applications/{application_id}/reject",
        "/api/v2/merchant/documents/{file_id}/url",
        "/api/v2/merchant/documents/{file_id}/content",
    }
    assert expected <= set(paths)
    detail = paths["/api/v2/merchant/kyc/applications/{application_id}"]["get"]
    schema = detail["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/MerchantKycApplicationResponseV2"}

    create = paths["/api/v2/merchant/customers"]["post"]
    create_schema = create["responses"]["201"]["content"]["application/json"]["schema"]
    assert create_schema == {"$ref": "#/components/schemas/MerchantCustomerResponseV2"}

    upload = paths["/api/v2/merchant/documents"]["post"]
    upload_schema = upload["responses"]["201"]["content"]["application/json"]["schema"]
    assert upload_schema == {"$ref": "#/components/schemas/DocumentUploadResponseV2"}


def test_delivery_v2_mixed_payment_routes_are_separate() -> None:
    openapi = app.openapi()
    paths = openapi["paths"]
    prefix = "/api/v2/delivery/deliveries/{deliveryId}"
    expected = {
        f"{prefix}/generate-qr",
        f"{prefix}/payment-proof",
        f"{prefix}/confirm",
        f"{prefix}/verify-customer-otp",
        f"{prefix}/payment-summary",
        f"{prefix}/completed-detail",
    }
    assert expected <= set(paths)
    assert not any(path.startswith("/api/v2/delivery/auth/") for path in paths)
    schema = paths[f"{prefix}/confirm"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    assert schema == {"$ref": "#/components/schemas/ConfirmDeliveryRequestV2"}
    assert openapi["components"]["schemas"]["PaymentMethodV2"]["enum"] == [
        "CASH",
        "UPI",
        "MIXED",
    ]


def test_delivery_v1_confirm_contract_does_not_change() -> None:
    operation = app.openapi()["paths"][
        "/api/v1/delivery/deliveries/{deliveryId}/confirm"
    ]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/ConfirmDeliveryRequest"}
