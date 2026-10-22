"""Merchant-facing response contracts for multi-image KYC review."""

from pydantic import BaseModel, ConfigDict, Field

from app.modules.customers.business_schemas import (
    CustomerRegistrationRequest,
    CustomerResponse,
    KycApplicationResponse,
)
from app.modules.customers.v2_schemas import DocumentFileResponseV2, DocumentSubmissionV2


class MerchantCustomerRegistrationRequestV2(CustomerRegistrationRequest):
    documents: list[DocumentSubmissionV2]


class KycDocumentResponseV2(BaseModel):
    id: str
    type: str
    number_masked: str = Field(alias="numberMasked")
    status: str
    files: list[DocumentFileResponseV2]

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class MerchantKycApplicationResponseV2(KycApplicationResponse):
    documents: list[KycDocumentResponseV2]


class MerchantCustomerResponseV2(CustomerResponse):
    documents: list[KycDocumentResponseV2]


class MerchantKycApplicationListResponseV2(BaseModel):
    items: list[MerchantKycApplicationResponseV2]
    total: int
    limit: int
    offset: int
