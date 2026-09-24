import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach } from "vitest";

import { tokenStorage } from "../auth/token-storage";

// Route modules are lazy-loaded; the first import in a test file can take over a second.
configure({ asyncUtilTimeout: 5000 });

// Warm up lazily loaded route modules once per test file so the first navigation in a test
// does not depend on how fast Vitest transforms the page module.
beforeAll(async () => {
  await Promise.all([
    import("../features/dashboard/DashboardPage"),
    import("../features/merchants/MerchantsListPage"),
    import("../features/merchants/MerchantCreatePage"),
    import("../features/merchants/MerchantDetailPage"),
    import("../features/users/UsersPage"),
    import("../features/users/UserDetailPage"),
    import("../features/roles/RolesPage"),
    import("../features/roles/RoleDetailPage"),
    import("../features/permissions/PermissionsPage"),
    import("../features/audit-logs/AuditLogsPage"),
    import("../features/profile/ProfilePage"),
    import("../features/merchant-dashboard/MerchantDashboardPage"),
    import("../features/delivery-team/DeliveryTeamListPage"),
    import("../features/delivery-team/DeliveryMemberCreatePage"),
    import("../features/delivery-team/DeliveryMemberDetailPage")
  ]);
}, 60_000);

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
  tokenStorage.resetCache();
});

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  tokenStorage.resetCache();
});

// React Router's data router builds a Node `Request` with jsdom's AbortSignal, which Node's
// fetch implementation rejects. Tests don't need request cancellation, so drop the signal.
const NodeRequest = globalThis.Request;
globalThis.Request = class extends NodeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    if (init?.signal) {
      const { signal: _signal, ...rest } = init;
      void _signal;
      super(input, rest);
    } else {
      super(input, init);
    }
  }
} as typeof Request;

// jsdom does not implement scrolling.
window.scrollTo = () => undefined;
