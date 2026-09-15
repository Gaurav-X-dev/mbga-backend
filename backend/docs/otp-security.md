# OTP Security

Implemented design requirements:

- Normalize mobile numbers before lookup.
- Treat OTP as a string with exactly 4 digits; values such as `0123` are valid when generated.
- Bind each challenge to purpose and login channel.
- Store OTP hash only.
- Track expiry, attempts, resend cooldown, request metadata, and consumption timestamp.
- Reject replay after consumption.
- Use generic safe error codes.

Local development may use a development SMS provider abstraction. The temporary fixed OTP is configured only through `backend/.env`; the actual value must not be written into source, docs, frontend environment files, or Excel. Production/staging must fail closed when fixed OTP is enabled.

Database-backed OTP challenges are suitable for local development and tests. They are not a distributed rate-limiting replacement for Redis.
