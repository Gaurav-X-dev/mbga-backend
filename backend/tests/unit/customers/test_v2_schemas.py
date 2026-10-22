import pytest
from pydantic import ValidationError

from app.modules.customers.v2_schemas import DocumentSubmissionV2


def _file(file_id: str, side: str) -> dict:
    return {"fileId": file_id, "fileName": f"{side}.jpg", "side": side, "source": "CAMERA"}


def test_v2_document_accepts_two_distinct_sides() -> None:
    value = DocumentSubmissionV2.model_validate(
        {
            "type": "AADHAAR",
            "number": "123412341234",
            "files": [_file("front", "FRONT"), _file("back", "BACK")],
            "fileId": "front",
            "fileIds": ["front", "back"],
        }
    )
    assert [item.file_id for item in value.files] == ["front", "back"]


def test_v2_document_rejects_more_than_two_files() -> None:
    with pytest.raises(ValidationError):
        DocumentSubmissionV2.model_validate(
            {
                "type": "AADHAAR",
                "number": "123412341234",
                "files": [
                    _file("front", "FRONT"),
                    _file("back", "BACK"),
                    _file("page", "PAGE_1"),
                ],
            }
        )


def test_legacy_file_ids_must_match_canonical_files() -> None:
    with pytest.raises(ValidationError):
        DocumentSubmissionV2.model_validate(
            {
                "type": "AADHAAR",
                "number": "123412341234",
                "files": [_file("front", "FRONT")],
                "fileId": "different",
            }
        )


def test_v2_document_accepts_dynamic_document_types() -> None:
    value = DocumentSubmissionV2.model_validate(
        {
            "type": "trade_license",
            "number": "TL-999",
            "files": [_file("doc_1", "FRONT")],
        }
    )
    assert value.type == "TRADE_LICENSE"


def test_v2_profile_payload_accepts_dynamic_customer_type() -> None:
    from app.modules.customers.v2_schemas import CustomerProfileV2Payload

    payload = CustomerProfileV2Payload.model_validate(
        {
            "merchant_code": "MERCH1",
            "customer_type": "commercial_bulk",
            "name": "Acme Corp",
        }
    )
    assert payload.customer_type == "COMMERCIAL_BULK"
