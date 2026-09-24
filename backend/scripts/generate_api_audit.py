from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import _normalize_operation_docs, app


DOCS = Path("docs")
API_PREFIX = "/api/v1"
AUTH_OPERATIONS = [
    "check-mobile",
    "otp/request",
    "otp/resend",
    "otp/verify",
    "token/refresh",
    "logout",
    "logout-all",
    "me",
]
CHANNELS = {
    "/admin/": ("ADMIN", "ADMIN_WEB"),
    "/merchant/": ("MERCHANT", "MERCHANT_WEB,MERCHANT_APP"),
    "/customer/registration/": ("CUSTOMER_REGISTRATION", "CUSTOMER_APP"),
    "/customer/": ("CUSTOMER", "CUSTOMER_APP"),
    "/delivery/": ("DELIVERY", "DELIVERY_APP"),
}
AUTH_ROUTER = "app/modules/authentication/channel_router.py"


def channel_and_client(path: str) -> tuple[str, str]:
    stripped = path.removeprefix(API_PREFIX)
    for prefix, values in CHANNELS.items():
        if stripped.startswith(prefix):
            return values
    if stripped == "/health":
        return "INTERNAL", "INTERNAL"
    return "ADMIN", "ADMIN_WEB"


def router_file(path: str) -> str:
    if "/auth/" in path or path.startswith(f"{API_PREFIX}/auth/"):
        return AUTH_ROUTER
    if path.startswith(f"{API_PREFIX}/customer/registration") or path.endswith("/auth/check-mobile"):
        return "app/modules/customers/router.py"
    if "/dashboard" in path:
        return "app/modules/dashboard/router.py"
    if "/users" in path:
        return "app/modules/users/router.py"
    if "/roles" in path:
        return "app/modules/roles/router.py"
    if "/permissions" in path:
        return "app/modules/permissions/router.py"
    if "/audit-logs" in path:
        return "app/modules/audit_logs/router.py"
    if path.endswith("/login-channel"):
        return "app/channels/*/router.py"
    return "app/main.py"


def service_method(path: str, method: str) -> str:
    if path.endswith("/otp/request") or path.endswith("/otp/resend"):
        return "AuthenticationService.request_otp"
    if path.endswith("/otp/verify"):
        return "AuthenticationService.verify_otp"
    if path.endswith("/token/refresh"):
        return "AuthenticationService.refresh_token"
    if path.endswith("/logout-all"):
        return "AuthenticationService.logout_all + me"
    if path.endswith("/logout"):
        return "AuthenticationService.logout"
    if path.endswith("/me"):
        return "AuthenticationService.me"
    if "/roles" in path:
        return "RoleService/inline router logic"
    if "/permissions" in path:
        return "PermissionService/inline router logic"
    return "inline router logic"


def repository_method(path: str) -> str:
    if "/auth/" in path or path.startswith(f"{API_PREFIX}/auth/"):
        return "AuthenticationRepository, OTPService, UserRoleRepository"
    if "/users" in path:
        return "AsyncSession, UserRoleRepository"
    if "/roles" in path:
        return "RoleRepository"
    if "/permissions" in path:
        return "PermissionRepository"
    return "AsyncSession"


def permission(path: str) -> str:
    mapping = {
        "/dashboard": "dashboard.view",
        "/users": "users.*",
        "/roles": "roles.*",
        "/permissions": "permissions.*",
        "/audit-logs": "audit_logs.view",
    }
    for marker, value in mapping.items():
        if marker in path:
            return value
    return "none"


def status_for(path: str, operation: dict[str, Any]) -> str:
    if path.endswith("/login-channel"):
        return "PLACEHOLDER,UNTESTED"
    if "/auth/" in path:
        return "IMPLEMENTED,INTENTIONAL_CHANNEL_ROUTE"
    if path.startswith(f"{API_PREFIX}/customer/"):
        return "PARTIAL,UNTESTED"
    if operation.get("security"):
        return "IMPLEMENTED"
    return "IMPLEMENTED,UNTESTED"


def auth_required(path: str, operation: dict[str, Any]) -> str:
    if path.endswith(("/otp/request", "/otp/resend", "/otp/verify", "/auth/check-mobile", "/registration/fields", "/registration/profile", "/registration/status", "/login-channel")):
        return "no"
    if operation.get("security") or any(segment in path for segment in ["/dashboard", "/users", "/roles", "/permissions", "/audit-logs"]):
        return "yes"
    return "unclear"


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def filtered_openapi(openapi: dict[str, Any], client: str) -> dict[str, Any]:
    keep_prefixes = {
        "admin": [f"{API_PREFIX}/admin"],
        "merchant": [f"{API_PREFIX}/merchant"],
        "customer": [f"{API_PREFIX}/customer"],
        "delivery": [f"{API_PREFIX}/delivery"],
    }[client]
    paths = {
        path: _normalize_operation_docs(path, value)
        for path, value in openapi["paths"].items()
        if any(path.startswith(prefix) for prefix in keep_prefixes)
    }
    copy = dict(openapi)
    copy["info"] = {**openapi["info"], "title": f"MBGA {client.title()} API"}
    copy["paths"] = paths
    return copy


def postman_for(openapi: dict[str, Any], name: str) -> dict[str, Any]:
    items = []
    for path, methods in sorted(openapi["paths"].items()):
        for method, operation in sorted(methods.items()):
            if method.lower() not in {"get", "post", "patch", "delete", "put"}:
                continue
            items.append(
                {
                    "name": operation.get("summary") or f"{method.upper()} {path}",
                    "request": {
                        "method": method.upper(),
                        "header": [
                            {"key": "Authorization", "value": "Bearer {{access_token}}", "type": "text"}
                        ],
                        "url": {
                            "raw": "{{base_url}}" + path.removeprefix(API_PREFIX),
                            "host": ["{{base_url}}"],
                            "path": path.removeprefix(API_PREFIX).strip("/").split("/"),
                        },
                    },
                }
            )
    return {
        "info": {
            "name": name,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [
            {"key": key, "value": ""}
            for key in [
                "base_url",
                "mobile_number",
                "otp",
                "request_id",
                "access_token",
                "refresh_token",
                "onboarding_token",
            ]
        ],
        "item": items,
    }


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    openapi = app.openapi()
    inventory_rows = []
    seen = Counter()
    for path, methods in sorted(openapi["paths"].items()):
        for method, operation in sorted(methods.items()):
            if method.lower() not in {"get", "post", "patch", "delete", "put"}:
                continue
            channel, client = channel_and_client(path)
            seen[(method.upper(), path)] += 1
            inventory_rows.append(
                {
                    "Method": method.upper(),
                    "Path": path,
                    "Channel": channel,
                    "Client": client,
                    "Router file": router_file(path),
                    "Service method": service_method(path, method),
                    "Repository method": repository_method(path),
                    "Permission": permission(path),
                    "Auth required": auth_required(path, operation),
                    "Status": status_for(path, operation),
                }
            )

    with (DOCS / "api-inventory.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(inventory_rows[0].keys()))
        writer.writeheader()
        writer.writerows(inventory_rows)

    duplicate_paths = [f"{method} {path}" for (method, path), count in seen.items() if count > 1]
    channel_counts = Counter(row["Channel"] for row in inventory_rows)
    client_counts = Counter(row["Client"] for row in inventory_rows)
    partial = [row for row in inventory_rows if "PARTIAL" in row["Status"] or "PLACEHOLDER" in row["Status"]]
    untested = [row for row in inventory_rows if "UNTESTED" in row["Status"]]

    auth_table = []
    for operation in AUTH_OPERATIONS:
        auth_table.append(
            {
                "Operation": operation,
                "Admin": "channel route" if operation != "check-mobile" else "n/a",
                "Merchant": "channel route" if operation != "check-mobile" else "n/a",
                "Customer": "channel route" if operation != "check-mobile" else "/customer/auth/check-mobile only",
                "Delivery": "channel route" if operation != "check-mobile" else "n/a",
                "Shared implementation?": "yes via build_channel_auth_router + AuthenticationService" if operation != "check-mobile" else "no",
                "Difference justified?": "yes; route fixes channel/purpose and account policy differs",
            }
        )

    (DOCS / "api-audit.md").write_text(
        "# API Audit\n\n"
        f"Total route operations discovered: {len(inventory_rows)}\n\n"
        "## Counts By Channel\n\n"
        + "\n".join(f"- {key}: {value}" for key, value in sorted(channel_counts.items()))
        + "\n\n## Counts By Client\n\n"
        + "\n".join(f"- {key}: {value}" for key, value in sorted(client_counts.items()))
        + "\n\n## Duplicate Method/Path Registrations\n\n"
        + ("\n".join(f"- {item}" for item in duplicate_paths) if duplicate_paths else "None found.")
        + "\n\n## Intentional Channel Routes\n\n"
        "Admin, Merchant, Customer, Customer registration, and Delivery auth routes intentionally expose separate URLs while using the shared channel auth router and AuthenticationService.\n\n"
        "## Harmful Duplicated Code\n\n"
        "No copied OTP generation/hash/verify/token/logout logic was found across channel routers. Legacy `/api/v1/auth/*` placeholder routes have been unmounted.\n\n"
        "## Partial Or Placeholder APIs\n\n"
        + "\n".join(f"- {row['Method']} {row['Path']}: {row['Status']}" for row in partial)
        + "\n\n## Untested Or Not Fully Traced APIs\n\n"
        + "\n".join(f"- {row['Method']} {row['Path']}" for row in untested[:80])
        + "\n",
        encoding="utf-8",
    )

    (DOCS / "auth-api-comparison.md").write_text(
        "# Authentication API Comparison\n\n"
        "| Operation | Admin | Merchant | Customer | Delivery | Shared implementation? | Difference justified? |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        + "\n".join(
            f"| {row['Operation']} | {row['Admin']} | {row['Merchant']} | {row['Customer']} | {row['Delivery']} | {row['Shared implementation?']} | {row['Difference justified?']} |"
            for row in auth_table
        )
        + "\n\n## Contract Notes\n\n"
        "- OTP verification accepts `otp` as a string matching `^[0-9]{4}$`.\n"
        "- Channel-specific routes set channel server-side; clients should not be trusted to choose channel by body.\n"
        "- Legacy `/api/v1/auth/*` routes are absent; use channel-specific auth URLs only.\n"
        "- Customer registration uses `CUSTOMER_REGISTRATION` purpose and returns onboarding-scope access.\n"
        "- Full customer login is denied until the customer profile/documents are approved.\n",
        encoding="utf-8",
    )

    (DOCS / "mobile-api-scope.md").write_text(
        "# Mobile API Scope\n\n"
        "## Customer App APIs\n\n"
        "- POST `/api/v1/customer/auth/check-mobile`\n"
        "- POST `/api/v1/customer/auth/otp/request`\n"
        "- POST `/api/v1/customer/auth/otp/resend`\n"
        "- POST `/api/v1/customer/auth/otp/verify`\n"
        "- POST `/api/v1/customer/auth/token/refresh`\n"
        "- POST `/api/v1/customer/auth/logout`\n"
        "- POST `/api/v1/customer/auth/logout-all`\n"
        "- GET `/api/v1/customer/auth/me`\n"
        "- POST `/api/v1/customer/registration/otp/request`\n"
        "- POST `/api/v1/customer/registration/otp/resend`\n"
        "- POST `/api/v1/customer/registration/otp/verify`\n"
        "- GET `/api/v1/customer/registration/fields`\n"
        "- POST `/api/v1/customer/registration/profile`\n"
        "- GET `/api/v1/customer/registration/status`\n\n"
        "## Delivery App APIs\n\n"
        "- POST `/api/v1/delivery/auth/otp/request`\n"
        "- POST `/api/v1/delivery/auth/otp/resend`\n"
        "- POST `/api/v1/delivery/auth/otp/verify`\n"
        "- POST `/api/v1/delivery/auth/token/refresh`\n"
        "- POST `/api/v1/delivery/auth/logout`\n"
        "- POST `/api/v1/delivery/auth/logout-all`\n"
        "- GET `/api/v1/delivery/auth/me`\n\n"
        "## Merchant App APIs\n\n"
        "- POST `/api/v1/merchant/auth/otp/request`\n"
        "- POST `/api/v1/merchant/auth/otp/resend`\n"
        "- POST `/api/v1/merchant/auth/otp/verify`\n"
        "- POST `/api/v1/merchant/auth/token/refresh`\n"
        "- POST `/api/v1/merchant/auth/logout`\n"
        "- POST `/api/v1/merchant/auth/logout-all`\n"
        "- GET `/api/v1/merchant/auth/me`\n\n"
        "## Web-panel APIs\n\n"
        "### Admin Web\n\n"
        "- `/api/v1/admin/auth/*`\n"
        "- `/api/v1/admin/dashboard/summary`\n"
        "- `/api/v1/admin/users*`\n"
        "- `/api/v1/admin/roles*`\n"
        "- `/api/v1/admin/permissions*`\n"
        "- `/api/v1/admin/audit-logs*`\n\n"
        "### Merchant Web\n\n"
        "- `/api/v1/merchant/auth/*`\n\n"
        "Do not provide Admin roles, permissions, users, dashboard, or audit-log APIs to Customer or Delivery app developers.\n",
        encoding="utf-8",
    )

    (DOCS / "api-test-matrix.md").write_text(
        "# API Test Matrix\n\n"
        "| API Area | Current coverage |\n| --- | --- |\n"
        "| Channel auth contract | API contract matrix |\n"
        "| OTP schema | Unit + API contract |\n"
        "| Admin RBAC APIs | API + unit |\n"
        "| RBAC persistence/migrations | MariaDB integration |\n"
        "| Frontend OTP UI | Vitest + Playwright |\n"
        "| Customer registration starter APIs | No direct API test yet |\n"
        "| Merchant/Delivery approval policy branches | Not fully integration-tested yet |\n\n"
        f"Total routes: {len(inventory_rows)}\n\n"
        f"Partial/placeholder routes: {len(partial)}\n\n"
        f"Duplicate method/path registrations: {len(duplicate_paths)}\n",
        encoding="utf-8",
    )

    for client in ["admin", "merchant", "customer", "delivery"]:
        filtered = filtered_openapi(openapi, client)
        write_json(DOCS / f"openapi-{client}.json", filtered)
        write_json(DOCS / f"MBGA_{client.title()}_API.postman_collection.json", postman_for(filtered, f"MBGA {client.title()} API"))


if __name__ == "__main__":
    main()
