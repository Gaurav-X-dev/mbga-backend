# API Reference

This document tracks implemented API contracts. It should be updated as endpoints become fully functional.

## Authentication

Mobile OTP endpoints are channel-specific and share central services:

- `/api/v1/admin/auth/otp/request`
- `/api/v1/merchant/auth/otp/request`
- `/api/v1/customer/auth/otp/request`
- `/api/v1/delivery/auth/otp/request`

## Customer Registration

- `/api/v1/customer/registration/fields`
- `/api/v1/customer/registration/profile`
- `/api/v1/customer/registration/documents`
- `/api/v1/customer/registration/submit`
- `/api/v1/customer/registration/status`

## RBAC

RBAC admin APIs remain under `/api/v1/admin`.
