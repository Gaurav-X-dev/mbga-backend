# Proposed Role Permission Matrix

This document is review-only. These business-role grants are not seeded.

`super_admin` is the only role that currently receives all supported permissions explicitly from the seed runner. Other roles retain no guessed permission grants until product approval.

| Role | Proposed module | Proposed permission | Proposed access | Reason/source | Approval status | Open question |
| --- | --- | --- | --- | --- | --- | --- |
| customer | orders | orders.view | Own scoped records only | SRS customer app flow | PROPOSED_NOT_SEEDED | Confirm self-service order history scope. |
| customer | payments | payments.view | Own scoped records only | SRS payment visibility | PROPOSED_NOT_SEEDED | Confirm whether ledger/payment detail is visible. |
| driver | deliveries | deliveries.view | Assigned delivery records | SOW delivery workflow | PROPOSED_NOT_SEEDED | Confirm driver/helper split. |
| driver | deliveries | deliveries.update_status | Assigned delivery records | SOW delivery workflow | PROPOSED_NOT_SEEDED | Confirm allowed status transitions. |
| helper | deliveries | deliveries.view | Assigned/helper records | SOW delivery workflow | PROPOSED_NOT_SEEDED | Confirm whether helpers update statuses. |
| manager | orders | orders.view | Merchant scoped records | SRS merchant/admin operations | PROPOSED_NOT_SEEDED | Confirm merchant-vs-admin channel boundary. |
| manager | orders | orders.create | Merchant scoped records | SRS merchant operations | PROPOSED_NOT_SEEDED | Confirm who creates orders. |
| manager | orders | orders.update | Merchant scoped records | SRS merchant operations | PROPOSED_NOT_SEEDED | Confirm cancellation/assignment authority. |
| manager | inventory | inventory.view | Merchant/godown scope | Screen-field spreadsheet | PROPOSED_NOT_SEEDED | Confirm scope by merchant/godown. |
| salesperson | orders | orders.create | Merchant/customer scope | SOW sales process | PROPOSED_NOT_SEEDED | Confirm whether salesperson can update pricing. |
| godown_stock_manager | inventory | inventory.view | Godown scope | Screen-field spreadsheet | PROPOSED_NOT_SEEDED | Confirm multi-godown scope model. |
| godown_stock_manager | inventory | inventory.adjust | Godown scope | Screen-field spreadsheet | PROPOSED_NOT_SEEDED | Confirm approval needed for adjustments. |
| accountant | payments | payments.reconcile | Merchant/accounting scope | SOW payment reconciliation | PROPOSED_NOT_SEEDED | Confirm export/report permissions. |
| accountant | ledgers | ledgers.view | Merchant/accounting scope | SOW reconciliation | PROPOSED_NOT_SEEDED | Confirm ledger mutation requirements. |
| super_admin | all supported modules | all current permissions | Global admin | System bootstrap | SEEDED | Keep explicit rows, no wildcard bypass. |
