# MBGA Backend Working Notes

Date: 2026-09-14

## Source Documents Reviewed

- `docs/SoW-Order Management and Payment Recon System for MBGA (2).docx`
- `docs/MBGA_SRS_Phase1_Redesigned_No_Duplicacy_2026-09-04.docx`
- `docs/MBGA_Screen_Field_Role_Specification-2.xlsx`

## Tech Direction

- Backend: Python + FastAPI
- Database: MySQL
- Architecture style: modular monolith first, with clear module boundaries
- API style: REST, versioned under `/api/v1`
- Auth: role-based access control enforced at API/service layer
- Apps supported by same backend:
  - Merchant App: Manager, Salesperson, Godown Stock Manager, Accountant
  - Customer App: Retail and Industrial customers
  - Delivery App: Driver and Helper

## Phase 1 Core Modules

1. Auth and Users
   - Login, staff/customer identities, role management
   - Roles: Manager, Salesperson, Godown Stock Manager, Accountant, Driver, Helper, Customer
   - Manager-only staff and role administration

2. Customer Management and KYC
   - Retail and Industrial customer profiles
   - Retail documents: Aadhaar and PAN
   - Industrial documents: FSSAI and GST
   - Aadhaar must be masked/hashed only; no raw plain-text storage
   - Verification workflow: pending, approved, rejected, rejection reason
   - Industrial multi-site support and customer delivery addresses

3. Pricing
   - Monthly customer-wise pricing
   - BPCL base rate plus priority tier override
   - Pricing per cylinder type
   - Price change log with previous value, changed by, timestamp
   - Monthly pricing reminder

4. Orders
   - Verified customers can place orders only after approval
   - Cylinder type and quantity order lines
   - Repeat last order
   - Applicable price shown before confirmation
   - Phase 1 minimum statuses: confirmed, dispatched, delivered
   - Cutoff and next-day auto-scheduling are flagged for confirmation

5. Delivery and Dispatch
   - Godown allocation of cylinders to orders
   - Digital delivery slip
   - Driver/helper assignment
   - Ordered vs delivered quantities
   - Empty-cylinder collection
   - Pending pickup list when empties are not collected
   - OTP or signature delivery confirmation

6. Payments and Reconciliation
   - Split payments: cash, UPI, NEFT
   - Payment linked to order/invoice
   - Overpayment, underpayment, matched flags
   - Invalid payment marking by Accountant/Manager only
   - Customer running balance: due/advance
   - Daily payment collection report

7. Inventory / Godown Stock
   - Filled, empty, defective stock by cylinder type
   - Auto decrease filled stock on dispatch
   - Auto increase empty stock on delivery exchange
   - Reorder thresholds and low-stock alerts

8. Notifications
   - In-app and email notifications
   - Order milestones and operational exceptions
   - SMS/WhatsApp and AI voice calling are not Phase 1 unless confirmed

9. Tasks and Escalations
   - Exception-driven tasks for pending pickup, payment due, reorder break
   - Assignee, SLA due time, escalation status

10. Expenses
    - Salary and daily operational costs
    - Period-wise expense listing

11. Reports
    - Daily delivery report
    - Payment collection report
    - Pending cylinder pickup report

## Master Data

Cylinder types for Phase 1:

- 5 kg
- 10 kg
- 19 kg
- 47.5 kg Liquid
- 47.5 kg Vapor
- 422 kg Hippo

## Proposed FastAPI Project Structure

```text
mbga-backend/
  app/
    __init__.py
    main.py
    api/
      __init__.py
      deps.py
      v1/
        __init__.py
        router.py
        endpoints/
          auth.py
          users.py
          customers.py
          kyc.py
          pricing.py
          orders.py
          delivery.py
          payments.py
          inventory.py
          notifications.py
          tasks.py
          expenses.py
          reports.py
    core/
      __init__.py
      config.py
      security.py
      permissions.py
      exceptions.py
    db/
      __init__.py
      base.py
      session.py
      migrations/
    models/
      __init__.py
      user.py
      customer.py
      kyc_document.py
      pricing.py
      order.py
      delivery.py
      payment.py
      ledger.py
      inventory.py
      notification.py
      task.py
      expense.py
    schemas/
      __init__.py
      auth.py
      user.py
      customer.py
      kyc_document.py
      pricing.py
      order.py
      delivery.py
      payment.py
      inventory.py
      notification.py
      task.py
      expense.py
      report.py
    services/
      __init__.py
      auth_service.py
      customer_service.py
      kyc_service.py
      pricing_service.py
      order_service.py
      delivery_service.py
      payment_service.py
      inventory_service.py
      notification_service.py
      task_service.py
      report_service.py
    repositories/
      __init__.py
      base.py
      users.py
      customers.py
      pricing.py
      orders.py
      delivery.py
      payments.py
      inventory.py
    workers/
      __init__.py
      reminders.py
      notifications.py
    utils/
      __init__.py
      date_time.py
      pagination.py
      file_storage.py
  tests/
    conftest.py
    api/
    services/
  docs/
  alembic.ini
  pyproject.toml
  README.md
  .env.example
  .gitignore
```

## Key Open Items For MBGA

- GitHub remote URL.
- Booking cutoff and next-day auto-reschedule: Phase 1 or Phase 2?
- Final role naming: Godown Stock Manager vs Godown In-Charge.
- Priority tier definitions and pricing formulas.
- Manual document verification vs third-party verification API.
- Escalation matrix and SLA windows.
- Hindi/regional language requirement.
- Whether manual vehicle trip logging is included in Phase 1.
- Whether proximity alerts, AI voice calling, SMS, or WhatsApp are deferred.

## Initial Implementation Order

1. Project bootstrap: FastAPI, SQLAlchemy, Alembic, Pydantic settings, MySQL driver.
2. Core config, database session, base model, health endpoint.
3. Auth/users/RBAC foundation.
4. Customer and KYC models/workflows.
5. Cylinder master data, pricing, and orders.
6. Inventory, delivery, payments, ledger.
7. Notifications, tasks, expenses, reports.
