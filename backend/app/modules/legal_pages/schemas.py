from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, TypeAdapter, field_validator
from pydantic.alias_generators import to_camel

from app.modules.payments.schemas import UtcTime


class View(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class Section(View):
    heading: str = Field(min_length=2, max_length=180)
    body: str = Field(min_length=10, max_length=10000)


class PolicyContent(View):
    title: str = Field(default="Privacy Policy", min_length=5, max_length=180)
    publisher_name: str = Field(min_length=2, max_length=200)
    customer_app_name: str = Field(min_length=2, max_length=150)
    merchant_app_name: str = Field(min_length=2, max_length=150)
    rider_app_name: str = Field(min_length=2, max_length=150)
    contact_email: str = Field(default="", max_length=254)
    contact_url: str = Field(default="", max_length=500)
    effective_date: date
    background_location: Literal["UNCONFIRMED", "FOREGROUND_ONLY", "FOREGROUND_AND_BACKGROUND"] = (
        "UNCONFIRMED"
    )
    sdk_disclosure: str = Field(default="", max_length=6000)
    sections: list[Section] = Field(min_length=1, max_length=40)

    @field_validator("sdk_disclosure")
    @classmethod
    def sdk_text(cls, value):
        if value and len(value) < 10:
            raise ValueError("Describe the providers and SDKs in at least 10 characters.")
        return value

    @field_validator("contact_email")
    @classmethod
    def email(cls, value):
        return str(TypeAdapter(EmailStr).validate_python(value)) if value else ""

    @field_validator("contact_url")
    @classmethod
    def url(cls, value):
        return str(TypeAdapter(HttpUrl).validate_python(value)) if value else ""

    @field_validator("title")
    @classmethod
    def privacy_title(cls, value):
        if "privacy" not in value.lower():
            raise ValueError("Title must identify this page as a privacy policy.")
        return value


class SaveDraft(View):
    expected_revision: int = Field(ge=0)
    content: PolicyContent


class PublishRequest(View):
    expected_revision: int = Field(ge=1)


class EditorResponse(View):
    slug: str = "privacy-policy"
    revision: int
    published_revision: int | None = None
    draft: PolicyContent
    published: PolicyContent | None = None
    updated_at: UtcTime | None = None
    updated_by: str | None = None
    published_at: UtcTime | None = None
    public_path: str = "/privacy-policy"
    publication_issues: list[str]


class PublicPolicy(View):
    slug: str = "privacy-policy"
    revision: int
    published_at: UtcTime
    content: PolicyContent


class RevisionResponse(View):
    id: str
    revision: int
    action: str
    actor_name: str
    created_at: UtcTime
    content: PolicyContent
