"""Payments vocabulary: invoice states, how money is collected, and when a payment is trusted.

Two objects, and the distinction between them is the whole module:

* An **invoice** is what the customer owes. It is raised once, against a delivered order, and
  from then on it only ever has money applied to it.
* A **payment** is one act of collecting. Several can land on one invoice - a customer paying
  half in cash today and the rest by UPI next week is ordinary - so an invoice's `paidAmount`
  is the sum of its payments, never a figure typed in by hand.

Money is whole rupees, as everywhere else on the platform, and GST is broken **out of** the
total rather than added on top (spec §18.1) - the invoice copies the order's split so the two
documents can never disagree about tax.
"""

from enum import StrEnum


class InvoiceStatus(StrEnum):
    """Spec §2 `InvoiceStatus`. Derived from the balance, never set directly."""

    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"
    PAID = "PAID"


class PaymentMode(StrEnum):
    """Spec §2 `PaymentMode`. How the money actually moved."""

    CASH = "CASH"
    UPI = "UPI"
    NEFT = "NEFT"


class ReconciliationStatus(StrEnum):
    """Whether the merchant's books trust this payment yet (spec §2).

    Cash is `RECONCILED` the moment it is recorded: the person typing it in is holding the
    notes. UPI and NEFT are `PENDING` until somebody matches the reference against a bank
    statement, because until then the only evidence is a screenshot the customer showed a
    driver. `INVALID` is what that match finds when the money never arrived.
    """

    PENDING = "PENDING"
    RECONCILED = "RECONCILED"
    INVALID = "INVALID"


#: Modes that are settled as soon as they are recorded. Anything else waits for a bank match.
SELF_EVIDENT_MODES: frozenset[PaymentMode] = frozenset({PaymentMode.CASH})

#: Modes that must carry a reference - a UTR, a UPI transaction id, a cheque number. Without one
#: the payment cannot be reconciled later, which makes recording it close to pointless.
REFERENCE_REQUIRED_MODES: frozenset[PaymentMode] = frozenset({PaymentMode.UPI, PaymentMode.NEFT})

#: `reconciliationStatus = ALL` on the list filter (spec §12.3).
ALL_STATUSES = "ALL"

#: A payment whose money never arrived stops counting against the invoice. It is **not** deleted:
#: it is evidence that somebody recorded a collection that turned out to be wrong, and the trail
#: of who recorded it is the point.
EXCLUDED_FROM_BALANCE: frozenset[ReconciliationStatus] = frozenset({ReconciliationStatus.INVALID})

#: How long a customer has to pay, in days from the invoice being issued. A platform-wide default
#: rather than a per-customer credit term: the spec has no field for one, and inventing a
#: negotiable term here would put a commercial decision in a constant.
DEFAULT_PAYMENT_TERM_DAYS = 7

#: Longest note or reason accepted on a payment.
MAX_NOTE_LENGTH = 500

#: Longest bank or UPI reference. Generous - UTRs, cheque numbers and UPI ids all differ.
MAX_REFERENCE_LENGTH = 80

#: A single payment above this is refused as a typo rather than accepted silently. One crore in
#: rupees: far beyond any cylinder delivery, and the common fat-finger is an extra zero.
MAX_PAYMENT_AMOUNT = 10_000_000
