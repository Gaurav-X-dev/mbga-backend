from datetime import datetime

from pydantic import BaseModel, Field, field_validator

#: NPCI's shape for a virtual payment address: a handle, an `@`, and the bank or app it
#: belongs to. Validated here rather than left to the customer's phone, because a malformed
#: VPA does not fail loudly - the QR renders, the driver shows it, and the payment app says
#: only that the address is invalid. The agency then has a delivery at the gate and no way
#: to take money for it.
UPI_ID_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9.\-_]{1,255}@[a-zA-Z][a-zA-Z0-9.\-]{1,63}$"


#: An IFSC is four letters for the bank, a zero, and six characters for the branch. The zero
#: is reserved, which is why it is spelled out rather than left as a wildcard: a typo there is
#: the difference between a transfer arriving and bouncing a week later.
IFSC_PATTERN = r"^[A-Z]{4}0[A-Z0-9]{6}$"


def _clean_upi_id(value: str | None) -> str | None:
    """A VPA with its spaces gone and its case settled.

    Typed-in addresses arrive with trailing spaces and mixed case often enough to be worth
    handling once here. UPI handles are not case-sensitive, so lowercasing is safe and makes
    two spellings of one address compare equal.
    """
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


class MerchantCreate(BaseModel):
    merchant_code: str = Field(min_length=2, max_length=80)
    business_name: str = Field(min_length=2, max_length=160)
    contact_person_name: str = Field(min_length=2, max_length=160)
    mobile_number: str = Field(min_length=6, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    gst_number: str | None = Field(default=None, max_length=30)
    address_line_1: str | None = Field(default=None, max_length=255)
    address_line_2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=20)
    #: The agency's own VPA. Money collected at the gate lands here, so it is deliberately
    #: an admin-only field: a merchant able to edit it could point an agency's collections
    #: at their own account.
    #:
    #: Required when creating. An agency without it cannot take a rupee at the gate - the
    #: driver app refuses to show a QR - so letting one be created without it only moves the
    #: discovery to a doorstep.
    upi_id: str = Field(min_length=3, max_length=120)
    #: The name the customer's payment app shows before they confirm. It is what tells them
    #: they are paying the right agency, so it is the agency's trading name, not a code.
    upi_payee_name: str = Field(min_length=2, max_length=160)

    @field_validator("upi_id")
    @classmethod
    def check_upi_id(cls, value: str) -> str:
        import re

        cleaned = _clean_upi_id(value)
        if not cleaned or not re.match(UPI_ID_PATTERN, cleaned):
            raise ValueError(
                "A UPI ID looks like name@bank, for example madhavgas@okhdfcbank."
            )
        return cleaned

    @field_validator("upi_payee_name")
    @classmethod
    def trim_payee_name(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Enter the name the customer's payment app should show.")
        return cleaned

    #: Printed on the invoice so a customer paying by NEFT has somewhere to send it. These go
    #: into the invoice's frozen snapshot at issue time, so changing them later does not
    #: rewrite invoices already raised.
    invoice_bank_name: str | None = Field(default=None, max_length=160)
    invoice_bank_account_name: str | None = Field(default=None, max_length=160)
    invoice_bank_account_number: str | None = Field(default=None, max_length=80)
    invoice_bank_ifsc: str | None = Field(default=None, max_length=30)

    @field_validator("invoice_bank_ifsc")
    @classmethod
    def check_ifsc(cls, value: str | None) -> str | None:
        import re

        cleaned = (value or "").strip().upper()
        if not cleaned:
            return None
        if not re.match(IFSC_PATTERN, cleaned):
            raise ValueError("An IFSC looks like HDFC0001234 - four letters, a zero, then six characters.")
        return cleaned

    @field_validator("invoice_bank_account_number")
    @classmethod
    def check_account_number(cls, value: str | None) -> str | None:
        cleaned = "".join(ch for ch in (value or "") if not ch.isspace())
        if not cleaned:
            return None
        if not cleaned.isalnum() or not 6 <= len(cleaned) <= 20:
            raise ValueError("An account number is 6 to 20 letters or digits, with no spaces.")
        return cleaned

    @field_validator("invoice_bank_name", "invoice_bank_account_name")
    @classmethod
    def trim_bank_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class MerchantUpdate(BaseModel):
    business_name: str | None = Field(default=None, min_length=2, max_length=160)
    contact_person_name: str | None = Field(default=None, min_length=2, max_length=160)
    email: str | None = Field(default=None, max_length=255)
    gst_number: str | None = Field(default=None, max_length=30)
    address_line_1: str | None = Field(default=None, max_length=255)
    address_line_2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=20)
    #: The agency's own VPA. Money collected at the gate lands here, so it is deliberately
    #: an admin-only field: a merchant able to edit it could point an agency's collections
    #: at their own account.
    upi_id: str | None = Field(default=None, max_length=120)
    #: The name the customer's payment app shows before they confirm. It is what tells them
    #: they are paying the right agency, so it is the agency's trading name, not a code.
    upi_payee_name: str | None = Field(default=None, max_length=160)

    @field_validator("upi_id")
    @classmethod
    def check_upi_id(cls, value: str | None) -> str | None:
        import re

        cleaned = _clean_upi_id(value)
        if cleaned is None:
            return None
        if not re.match(UPI_ID_PATTERN, cleaned):
            raise ValueError(
                "A UPI ID looks like name@bank, for example madhavgas@okhdfcbank."
            )
        return cleaned

    @field_validator("upi_payee_name")
    @classmethod
    def trim_payee_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    #: Printed on the invoice so a customer paying by NEFT has somewhere to send it. These go
    #: into the invoice's frozen snapshot at issue time, so changing them later does not
    #: rewrite invoices already raised.
    invoice_bank_name: str | None = Field(default=None, max_length=160)
    invoice_bank_account_name: str | None = Field(default=None, max_length=160)
    invoice_bank_account_number: str | None = Field(default=None, max_length=80)
    invoice_bank_ifsc: str | None = Field(default=None, max_length=30)

    @field_validator("invoice_bank_ifsc")
    @classmethod
    def check_ifsc(cls, value: str | None) -> str | None:
        import re

        cleaned = (value or "").strip().upper()
        if not cleaned:
            return None
        if not re.match(IFSC_PATTERN, cleaned):
            raise ValueError("An IFSC looks like HDFC0001234 - four letters, a zero, then six characters.")
        return cleaned

    @field_validator("invoice_bank_account_number")
    @classmethod
    def check_account_number(cls, value: str | None) -> str | None:
        cleaned = "".join(ch for ch in (value or "") if not ch.isspace())
        if not cleaned:
            return None
        if not cleaned.isalnum() or not 6 <= len(cleaned) <= 20:
            raise ValueError("An account number is 6 to 20 letters or digits, with no spaces.")
        return cleaned

    @field_validator("invoice_bank_name", "invoice_bank_account_name")
    @classmethod
    def trim_bank_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class MerchantResponse(BaseModel):
    id: str
    merchant_code: str
    business_name: str
    contact_person_name: str | None = None
    mobile_number: str | None = None
    email: str | None = None
    gst_number: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    upi_id: str | None = None
    upi_payee_name: str | None = None
    invoice_bank_name: str | None = None
    invoice_bank_account_name: str | None = None
    invoice_bank_account_number: str | None = None
    invoice_bank_ifsc: str | None = None
    #: True when both UPI fields are filled, which is what the driver app needs before it can
    #: put a QR on screen. Sent so the panel can say so plainly instead of leaving an operator
    #: to work out that half-filled details are the same as none.
    upi_ready: bool = False
    primary_user_id: str | None = None
    status: str
    approval_status: str
    role: str = "manager"
    allowed_channel: str = "MERCHANT"
    created_at: datetime


class MerchantListResponse(BaseModel):
    items: list[MerchantResponse]
    total: int
    limit: int
    offset: int


class MerchantUserCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    mobile_number: str = Field(min_length=6, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    staff_type: str = Field(default="MANAGER", max_length=60)


class MerchantUserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    email: str | None = Field(default=None, max_length=255)
    staff_type: str | None = Field(default=None, max_length=60)
    status: str | None = Field(default=None, max_length=30)


class MerchantUserResponse(BaseModel):
    id: str
    merchant_id: str
    user_id: str
    full_name: str | None = None
    mobile_number: str | None = None
    email: str | None = None
    staff_type: str | None = None
    status: str
    created_at: datetime
