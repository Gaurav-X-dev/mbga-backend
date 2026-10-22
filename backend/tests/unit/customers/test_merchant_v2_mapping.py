from datetime import UTC, datetime
from types import SimpleNamespace

from app.modules.customers.merchant_v2_schemas import MerchantCustomerRegistrationRequestV2
from app.modules.customers.merchant_v2_service import MerchantKycV2Service


def _document(file_id: str, name: str):
    return SimpleNamespace(
        id=file_id.removeprefix("doc_"),
        file_id=file_id,
        original_filename=name,
        file_size=100,
        mime_type="image/jpeg",
        document_type="AADHAAR",
        number_masked="XXXXXXXX1234",
        status="UPLOADED",
        submitted_at=datetime.now(UTC),
    )


def _mapping(file_id: str, side: str, order: int):
    return SimpleNamespace(
        document_type="AADHAAR",
        file_id=file_id,
        side=side,
        source="CAMERA",
        sort_order=order,
    )


def test_merchant_v2_document_contains_both_images() -> None:
    primary = _document("doc_front", "front.jpg")
    secondary = _document("doc_back", "back.jpg")
    service = MerchantKycV2Service(None)
    result = service._document_responses(
        [primary],
        [_mapping("doc_front", "FRONT", 1), _mapping("doc_back", "BACK", 2)],
        {"doc_front": primary, "doc_back": secondary},
    )
    assert [item.file_id for item in result[0].files] == ["doc_front", "doc_back"]
    assert [item.side.value for item in result[0].files] == ["FRONT", "BACK"]


def test_merchant_v2_legacy_document_gets_one_compatible_file() -> None:
    primary = _document("doc_legacy", "legacy.pdf")
    primary.mime_type = "application/pdf"
    service = MerchantKycV2Service(None)
    result = service._document_responses([primary], [], {})
    assert len(result[0].files) == 1
    assert result[0].files[0].file_id == "doc_legacy"
    assert result[0].files[0].side.value == "FRONT"


def test_merchant_v2_registration_accepts_front_and_back_files() -> None:
    request = MerchantCustomerRegistrationRequestV2.model_validate(
        {
            "customerType": "RETAIL",
            "mobile": "9876543210",
            "documents": [
                {
                    "type": "AADHAAR",
                    "number": "123412341234",
                    "files": [
                        {"fileId": "front", "side": "FRONT", "source": "CAMERA"},
                        {"fileId": "back", "side": "BACK", "source": "CAMERA"},
                    ],
                }
            ],
        }
    )
    assert [item.file_id for item in request.documents[0].files] == ["front", "back"]
