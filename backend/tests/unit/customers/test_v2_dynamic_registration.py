from unittest.mock import AsyncMock, patch
import pytest

from app.modules.customers.v2_schemas import (
    DocumentFileSubmissionV2,
    DocumentSide,
    DocumentSubmissionV2,
    UploadSource,
)
from app.modules.customers.v2_service import CustomerRegistrationV2Service
from app.shared.business.actor import BusinessActor
from app.shared.exceptions.api_error import ApiError


class DummyCustomerType:
    code = "HOTEL"
    label = "Hotel Customer"
    is_active = True


class DummyDocDef:
    def __init__(self, code: str, label: str, number_pattern: str | None = None, min_length: int | None = None, max_length: int | None = None):
        self.code = code
        self.label = label
        self.number_pattern = number_pattern
        self.min_length = min_length
        self.max_length = max_length


class DummyRule:
    def __init__(self, doc_code: str):
        self.document_type_code = doc_code
        self.requirement_mode = "REQUIRED"
        self.requirement_group = None
        self.min_required = 1


def _file(file_id: str, side: DocumentSide = DocumentSide.FRONT) -> DocumentFileSubmissionV2:
    return DocumentFileSubmissionV2(
        file_id=file_id,
        fileName=f"{file_id}.jpg",
        side=side,
        source=UploadSource.FILE_PICKER,
    )


@pytest.mark.asyncio
async def test_v2_prepare_validates_against_dynamic_catalogue_rules() -> None:
    session = AsyncMock()
    base = AsyncMock()
    access = AsyncMock()
    service = CustomerRegistrationV2Service(session, base=base, access=access)

    hotel_type = DummyCustomerType()
    doc_def = DummyDocDef("TRADE_LICENSE", "Trade License", r"^TL[0-9]{3}$", 5, 5)
    rule = DummyRule("TRADE_LICENSE")

    from app.modules.authentication.constants import LoginChannel
    actor = BusinessActor(user_id="usr_1", login_channel=LoginChannel.CUSTOMER, display_name="Test Customer")

    upload_mock = AsyncMock()
    upload_mock.file_id = "doc_file_1"
    access.attachable.return_value = upload_mock

    with (
        patch("app.modules.customers.v2_service.BusinessCatalogueService") as mock_catalogue_cls,
        patch.object(session, "scalars", return_value=AsyncMock(all=lambda: []))
    ):
        mock_catalogue = mock_catalogue_cls.return_value
        mock_catalogue.require_active_customer_type = AsyncMock(return_value=hotel_type)
        mock_catalogue.active_kyc_requirements = AsyncMock(return_value=[(rule, doc_def)])

        # 1. Valid submission for dynamic customer type HOTEL and dynamic document TRADE_LICENSE
        submission = DocumentSubmissionV2(
            type="TRADE_LICENSE",
            number="TL-123",
            files=[_file("doc_file_1")],
        )
        prepared = await service.prepare(None, actor, [submission], "HOTEL")
        assert len(prepared) == 1
        assert prepared[0].number == "TL123"
        assert prepared[0].submission.type == "TRADE_LICENSE"

        # 2. Ineligible document type for HOTEL customer type should be rejected
        ineligible_submission = DocumentSubmissionV2(
            type="GST",
            number="23AAACA1234F1Z5",
            files=[_file("doc_file_2")],
        )
        with pytest.raises(ApiError) as exc_info:
            await service.prepare(None, actor, [ineligible_submission], "HOTEL")
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["fields"][0]["code"] == "not_applicable"
