"""Unit tests for the Delivery App APIs and response envelopes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.modules.authentication.constants import LoginChannel
from app.shared.authorization.context import AuthContext
from app.shared.authorization.dependencies import require_authenticated_user

client = TestClient(app)


def test_auth_login_validation_error_on_empty_phone():
    response = client.post("/api/v1/delivery/auth/login", json={"phone": ""})
    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert payload["error"]["statusCode"] == 400


def test_auth_verify_otp_validation_error_on_short_code():
    response = client.post(
        "/api/v1/delivery/auth/verify-otp",
        json={"phone": "+919876543210", "otp": "12", "otpToken": "tok_123"},
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "VALIDATION_ERROR"


def test_auth_refresh_invalid_token():
    response = client.post(
        "/api/v1/delivery/auth/refresh",
        json={"refreshToken": "invalid-token"},
    )
    assert response.status_code == 401
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "TOKEN_EXPIRED"


def test_auth_logout_requires_bearer_token():
    response = client.post("/api/v1/delivery/auth/logout")
    assert response.status_code == 401
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "UNAUTHORIZED"


def test_unauthenticated_requests_return_error_envelope():
    endpoints = [
        ("GET", "/api/v1/delivery/deliveries/today"),
        ("GET", "/api/v1/delivery/deliveries/ORD123"),
        ("POST", "/api/v1/delivery/deliveries/ORD123/start"),
        ("POST", "/api/v1/delivery/deliveries/ORD123/confirm"),
        ("POST", "/api/v1/delivery/deliveries/ORD123/verify-customer-otp"),
        ("GET", "/api/v1/delivery/orders"),
        ("GET", "/api/v1/delivery/orders/history"),
        ("GET", "/api/v1/delivery/orders/ORD123"),
        ("GET", "/api/v1/delivery/driver/profile"),
        ("PATCH", "/api/v1/delivery/driver/status"),
        ("PATCH", "/api/v1/delivery/driver/language"),
        ("GET", "/api/v1/delivery/notifications"),
        ("PATCH", "/api/v1/delivery/notifications/notif-1/read"),
        ("GET", "/api/v1/delivery/driver/inventory"),
        ("GET", "/api/v1/delivery/payments/methods"),
        ("DELETE", "/api/v1/delivery/payments/methods/pm-1"),
        ("GET", "/api/v1/delivery/payments/history"),
    ]
    for method, path in endpoints:
        resp = client.request(method, path)
        assert resp.status_code == 401, f"Expected 401 for {method} {path}"
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "UNAUTHORIZED"
        assert data["error"]["statusCode"] == 401


def test_delivery_resources_reject_a_non_delivery_channel_session():
    """A valid token from another app channel must not access driver resources."""
    app.dependency_overrides[require_authenticated_user] = lambda: AuthContext(
        user_id="merchant-user", login_channel=LoginChannel.MERCHANT
    )
    try:
        response = client.get("/api/v1/delivery/deliveries/today")
        assert response.status_code == 403
        payload = response.json()
        assert payload["success"] is False
        assert payload["error"]["code"] == "FORBIDDEN"
    finally:
        app.dependency_overrides.clear()


class FakeDriverProfileService:
    async def get_profile(self, user_id: str):
        from app.modules.driver_profile.schemas import DriverProfileResponse
        return DriverProfileResponse(
            id=user_id,
            name="Ravi Kumar",
            phone="+919876543210",
            vehicleNumber="UP14 AB 1234",
            role="Driver",
            onDuty=True,
            avatarInitials="RK",
        )


def test_authenticated_driver_profile_success():
    from app.modules.driver_profile.router import get_driver_profile_service

    app.dependency_overrides[require_authenticated_user] = lambda: AuthContext(
        user_id="test-driver-user-id", login_channel=LoginChannel.DELIVERY
    )
    app.dependency_overrides[get_driver_profile_service] = lambda: FakeDriverProfileService()
    try:
        response = client.get("/api/v1/delivery/driver/profile")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["name"] == "Ravi Kumar"
        assert data["data"]["onDuty"] is True
        assert data["data"]["avatarInitials"] == "RK"
    finally:
        app.dependency_overrides.clear()


class FakeDeliveryService:
    async def get_today_deliveries(self, driver_user_id: str):
        return [
            {
                "id": "ORD1256",
                "orderNumber": "ORD1256",
                "customerName": "ABC Restaurant",
                "customerPhone": "+91 98765 43210",
                "address": "Sector 61, Noida",
                "status": "pending",
                "items": [
                    {"id": "item-1", "kind": "cylinderDelivery", "label": "19 KG Cylinder", "quantity": 5}
                ],
            }
        ]

    async def start_delivery(self, delivery_id: str, driver_user_id: str, latitude: float, longitude: float):
        from app.modules.deliveries.schemas import StartDeliveryResponse
        return StartDeliveryResponse(isAtLocation=True, distanceMetersFromDestination=42.0)

    async def confirm_delivery(self, delivery_id: str, driver_user_id: str, request):
        from app.modules.deliveries.schemas import ConfirmDeliveryResponse
        return ConfirmDeliveryResponse(deliveryId=delivery_id, customerOtpRequired=True)

    async def verify_customer_otp(self, delivery_id: str, driver_user_id: str, otp: str):
        from app.modules.deliveries.schemas import VerifyCustomerOtpResponse
        return VerifyCustomerOtpResponse(
            deliveryId=delivery_id,
            orderNumber="ORD1256",
            deliveredQuantity=5,
            emptyCollectedQuantity=4,
            completedAt="2026-09-23T12:00:00Z",
        )


def test_delivery_execution_lifecycle():
    from app.modules.deliveries.router import get_delivery_service

    app.dependency_overrides[require_authenticated_user] = lambda: AuthContext(
        user_id="driver-1", login_channel=LoginChannel.DELIVERY
    )
    app.dependency_overrides[get_delivery_service] = lambda: FakeDeliveryService()
    try:
        # Today's deliveries
        resp = client.get("/api/v1/delivery/deliveries/today")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["data"], list)
        assert data["data"][0]["orderNumber"] == "ORD1256"

        # Start delivery
        resp = client.post(
            "/api/v1/delivery/deliveries/ORD1256/start",
            json={"latitude": 28.5710, "longitude": 77.3620},
        )
        assert resp.status_code == 200
        start_data = resp.json()
        assert start_data["success"] is True
        assert start_data["data"]["isAtLocation"] is True

        # Confirm delivery
        resp = client.post(
            "/api/v1/delivery/deliveries/ORD1256/confirm",
            json={"deliveredQuantity": 5, "emptyCollectedQuantity": 4, "notes": "ok"},
        )
        assert resp.status_code == 200
        confirm_data = resp.json()
        assert confirm_data["success"] is True
        assert confirm_data["data"]["customerOtpRequired"] is True

        # Verify customer OTP
        resp = client.post(
            "/api/v1/delivery/deliveries/ORD1256/verify-customer-otp",
            json={"otp": "738104"},
        )
        assert resp.status_code == 200
        verify_data = resp.json()
        assert verify_data["success"] is True
        assert verify_data["data"]["deliveredQuantity"] == 5
    finally:
        app.dependency_overrides.clear()


class FakeInventoryService:
    async def get_driver_inventory(self, driver_user_id: str):
        from app.modules.inventory.schemas import DriverInventoryResponse
        return DriverInventoryResponse(
            fullCylinderCount=18,
            emptyCylinderCount=6,
            vehicleCapacity=30,
            lastUpdatedAt="2026-09-23T08:00:00Z",
        )


def test_driver_inventory():
    from app.modules.inventory.router import get_inventory_service

    app.dependency_overrides[require_authenticated_user] = lambda: AuthContext(
        user_id="driver-1", login_channel=LoginChannel.DELIVERY
    )
    app.dependency_overrides[get_inventory_service] = lambda: FakeInventoryService()
    try:
        resp = client.get("/api/v1/delivery/driver/inventory")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["fullCylinderCount"] == 18
        assert data["data"]["vehicleCapacity"] == 30
    finally:
        app.dependency_overrides.clear()
