# Requirements Conflicts And Missing Decisions

No blocking document conflicts were found for the initial authentication scaffold.

Missing decisions to confirm before full implementation:

- Whether Merchant staff login will use OTP, password, or both in production.
- Whether Admin login should use password, OTP, MFA, or a separate identity provider.
- Whether unknown mobile numbers should receive a generic OTP response or be rejected after customer/staff pre-registration.
- Final mapping between Delivery Partner, Driver, and Helper roles.
- Selected SMS provider and SMS template approval.
- Trusted proxy/IP forwarding setup for production rate limiting.
