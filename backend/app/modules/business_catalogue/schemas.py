from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CAMEL = ConfigDict(populate_by_name=True, serialize_by_alias=True, from_attributes=True)


def _code(value: str) -> str:
    value = value.strip().upper()
    if not value or len(value) > 40 or not all(c.isalnum() or c == "_" for c in value):
        raise ValueError("Use 1-40 uppercase letters, numbers or underscores.")
    return value


class CustomerTypeCreate(BaseModel):
    code: str
    label: str = Field(min_length=1, max_length=100)
    description: str | None = None
    code_prefix: str = Field(default="C", alias="codePrefix", min_length=1, max_length=8,
                             pattern=r"^[A-Za-z0-9]+$")
    requires_delivery_sites: bool = Field(default=False, alias="requiresDeliverySites")
    requires_gst_invoice: bool = Field(default=False, alias="requiresGstInvoice")
    is_default: bool = Field(default=False, alias="isDefault")
    sort_order: int = Field(default=0, alias="sortOrder", ge=0)
    model_config = CAMEL
    _normalise_code = field_validator("code")(_code)


class CustomerTypeUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    code_prefix: str | None = Field(default=None, alias="codePrefix", min_length=1, max_length=8,
                                    pattern=r"^[A-Za-z0-9]+$")
    requires_delivery_sites: bool | None = Field(default=None, alias="requiresDeliverySites")
    requires_gst_invoice: bool | None = Field(default=None, alias="requiresGstInvoice")
    is_default: bool | None = Field(default=None, alias="isDefault")
    is_active: bool | None = Field(default=None, alias="isActive")
    sort_order: int | None = Field(default=None, alias="sortOrder", ge=0)
    model_config = CAMEL


class CustomerTypeView(CustomerTypeCreate):
    is_active: bool = Field(alias="isActive")
    is_protected: bool = Field(alias="isProtected")


class CylinderTypeCreate(BaseModel):
    code: str
    label: str = Field(min_length=1, max_length=120)
    short_label: str | None = Field(default=None, alias="shortLabel", max_length=80)
    weight_kg: Decimal = Field(alias="weightKg", gt=0)
    variant: str | None = Field(default=None, max_length=40)
    hsn_sac: str | None = Field(default=None, alias="hsnSac", max_length=20)
    unit: str = Field(default="PCS", min_length=1, max_length=20)
    default_base_rate: Decimal = Field(default=0, alias="defaultBaseRate", ge=0)
    default_markup: Decimal = Field(default=0, alias="defaultMarkup", ge=0)
    gst_percent: Decimal = Field(default=18, alias="gstPercent", ge=0, le=100)
    reorder_threshold: int = Field(default=0, alias="reorderThreshold", ge=0)
    sort_order: int = Field(default=0, alias="sortOrder", ge=0)
    model_config = CAMEL
    _normalise_code = field_validator("code")(_code)


class CylinderTypeUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    short_label: str | None = Field(default=None, alias="shortLabel", max_length=80)
    weight_kg: Decimal | None = Field(default=None, alias="weightKg", gt=0)
    variant: str | None = Field(default=None, max_length=40)
    hsn_sac: str | None = Field(default=None, alias="hsnSac", max_length=20)
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    default_base_rate: Decimal | None = Field(default=None, alias="defaultBaseRate", ge=0)
    default_markup: Decimal | None = Field(default=None, alias="defaultMarkup", ge=0)
    gst_percent: Decimal | None = Field(default=None, alias="gstPercent", ge=0, le=100)
    reorder_threshold: int | None = Field(default=None, alias="reorderThreshold", ge=0)
    is_active: bool | None = Field(default=None, alias="isActive")
    sort_order: int | None = Field(default=None, alias="sortOrder", ge=0)
    model_config = CAMEL


class CylinderTypeView(CylinderTypeCreate):
    is_active: bool = Field(alias="isActive")
    is_protected: bool = Field(alias="isProtected")
    default_unit_price: Decimal = Field(alias="defaultUnitPrice")


class CylinderEligibilityItem(BaseModel):
    cylinder_type_code: str = Field(alias="cylinderTypeCode")
    min_quantity: int = Field(default=1, alias="minQuantity", ge=1)
    max_quantity: int | None = Field(default=None, alias="maxQuantity", ge=1)
    sort_order: int = Field(default=0, alias="sortOrder", ge=0)
    is_active: bool = Field(default=True, alias="isActive")
    model_config = CAMEL
    _normalise_cylinder_type_code = field_validator("cylinder_type_code")(_code)

    @model_validator(mode="after")
    def validate_range(self):
        if self.max_quantity is not None and self.max_quantity < self.min_quantity:
            raise ValueError("maxQuantity cannot be less than minQuantity")
        return self


class CylinderEligibilityReplace(BaseModel):
    items: list[CylinderEligibilityItem]


class KycDocumentTypeCreate(BaseModel):
    code: str
    label: str = Field(min_length=1, max_length=120)
    number_pattern: str | None = Field(default=None, alias="numberPattern", max_length=255)
    min_length: int | None = Field(default=None, alias="minLength", ge=1)
    max_length: int | None = Field(default=None, alias="maxLength", ge=1)
    expiry_required: bool = Field(default=False, alias="expiryRequired")
    scan_required: bool = Field(default=True, alias="scanRequired")
    sort_order: int = Field(default=0, alias="sortOrder", ge=0)
    model_config = CAMEL
    _normalise_code = field_validator("code")(_code)


class KycDocumentTypeUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    number_pattern: str | None = Field(default=None, alias="numberPattern", max_length=255)
    min_length: int | None = Field(default=None, alias="minLength", ge=1)
    max_length: int | None = Field(default=None, alias="maxLength", ge=1)
    expiry_required: bool | None = Field(default=None, alias="expiryRequired")
    scan_required: bool | None = Field(default=None, alias="scanRequired")
    is_active: bool | None = Field(default=None, alias="isActive")
    sort_order: int | None = Field(default=None, alias="sortOrder", ge=0)
    model_config = CAMEL


class KycDocumentTypeView(KycDocumentTypeCreate):
    is_active: bool = Field(alias="isActive")
    is_protected: bool = Field(alias="isProtected")


class KycRuleItem(BaseModel):
    document_type_code: str = Field(alias="documentTypeCode")
    requirement_mode: Literal["REQUIRED", "OPTIONAL", "ANY_OF"] = Field(alias="requirementMode")
    requirement_group: str | None = Field(default=None, alias="requirementGroup", max_length=60)
    min_required: int = Field(default=1, alias="minRequired", ge=1)
    is_active: bool = Field(default=True, alias="isActive")
    sort_order: int = Field(default=0, alias="sortOrder", ge=0)
    model_config = CAMEL
    _normalise_document_type_code = field_validator("document_type_code")(_code)


class KycRulesReplace(BaseModel):
    items: list[KycRuleItem]
