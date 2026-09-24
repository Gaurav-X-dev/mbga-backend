"""Validation, masking, file detection and identifier encryption."""

import pytest

from app.modules.customers.codes import format_code
from app.modules.customers.constants import CustomerType, KycDocumentType, to_mobile_account_status
from app.modules.customers.validators import (
    FieldErrors,
    clean_text,
    mask_document_number,
    normalize_document_number,
    validate_address,
    validate_document_number,
    validate_email,
)
from app.shared.crypto import FieldCipher
from app.shared.storage.file_types import detect_content_type, extension_matches, sanitize_filename

SECRET = "a-long-enough-local-test-secret-value"


class _Address:
    def __init__(self, **fields):
        self.__dict__.update({"line1": "", "line2": None, "city": "", "state": "", "pincode": "", **fields})


# --- document numbers -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "raw", "expected"),
    [
        (KycDocumentType.AADHAAR, "1234 5678 9012", "123456789012"),
        (KycDocumentType.AADHAAR, "1234-5678-9012", "123456789012"),
        (KycDocumentType.PAN, " abcde1234f ", "ABCDE1234F"),
        (KycDocumentType.GST, "23aaaca1234f1z5", "23AAACA1234F1Z5"),
        (KycDocumentType.FSSAI, "1234 5678 9012 34", "12345678901234"),
    ],
)
def test_people_type_identifiers_with_spaces_and_case(kind, raw, expected):
    """Formatting people actually type is normalised before the pattern is applied."""
    errors = FieldErrors()
    assert validate_document_number(kind, raw, errors) == expected
    assert not errors


@pytest.mark.parametrize(
    ("kind", "raw"),
    [
        (KycDocumentType.AADHAAR, "12345678901"),
        (KycDocumentType.AADHAAR, "1234567890123"),
        (KycDocumentType.AADHAAR, "12345678901A"),
        (KycDocumentType.PAN, "ABCDE1234"),
        (KycDocumentType.PAN, "ABCD01234F"),
        (KycDocumentType.FSSAI, "1234567890123"),
        (KycDocumentType.GST, "23AAACA1234F1A5"),
        (KycDocumentType.GST, "AA AACA1234F1Z5"),
        (KycDocumentType.PAN, ""),
    ],
)
def test_invalid_identifiers_are_refused(kind, raw):
    errors = FieldErrors()
    assert validate_document_number(kind, raw, errors) is None
    assert [item["field"] for item in errors.fields] == [f"doc.{kind.value}.number"]


@pytest.mark.parametrize(
    ("kind", "value", "masked"),
    [
        (KycDocumentType.AADHAAR, "123412344821", "XXXX XXXX 4821"),
        (KycDocumentType.PAN, "ABCDE1234F", "XXXXX1234F"),
        (KycDocumentType.FSSAI, "12345678907712", "XXXXXXXXXX7712"),
        (KycDocumentType.GST, "23AAACA1234F1Z5", "23XXXXXXXXXX1Z5"),
    ],
)
def test_masks_match_the_specification_examples(kind, value, masked):
    assert mask_document_number(kind, value) == masked


def test_a_mask_never_leaks_the_middle_of_an_identifier():
    value = "987654321098"
    assert value[:8] not in mask_document_number(KycDocumentType.AADHAAR, value)


# --- encryption -------------------------------------------------------------------------------


def test_an_identifier_round_trips_but_its_ciphertext_differs_each_time():
    cipher = FieldCipher(SECRET)
    first, second = cipher.encrypt("123412341234"), cipher.encrypt("123412341234")
    assert first != second, "a constant ciphertext would leak equality across rows"
    assert cipher.decrypt(first) == cipher.decrypt(second) == "123412341234"


def test_the_lookup_hash_is_stable_keyed_and_not_the_plain_digest():
    """Duplicate detection needs equality; a plain SHA-256 of an Aadhaar is brute-forceable."""
    import hashlib

    cipher = FieldCipher(SECRET)
    value = "123412341234"
    digest = cipher.lookup_hash(value)
    assert digest == cipher.lookup_hash(value)
    assert digest != hashlib.sha256(value.encode()).hexdigest()
    assert digest != FieldCipher("a-completely-different-secret-value").lookup_hash(value)


def test_a_key_that_cannot_read_a_value_returns_none_rather_than_raising():
    """A rotated secret must not turn a list endpoint into a 500."""
    token = FieldCipher(SECRET).encrypt("ABCDE1234F")
    assert FieldCipher("another-secret-entirely-for-this-test").decrypt(token) is None
    assert FieldCipher(SECRET).decrypt("not-a-token") is None


def test_a_cipher_built_for_one_purpose_cannot_read_another():
    token = FieldCipher(SECRET, purpose="kyc-document-number").encrypt("ABCDE1234F")
    assert FieldCipher(SECRET, purpose="bank-account").decrypt(token) is None


# --- addresses and email ------------------------------------------------------------------------


def test_a_valid_address_is_normalised():
    errors = FieldErrors()
    result = validate_address(
        _Address(line1="  12   MG  Road ", city=" Indore ", state="Madhya Pradesh", pincode="452 001"),
        errors,
    )
    assert not errors
    assert result == {"line1": "12 MG Road", "line2": None, "city": "Indore", "state": "Madhya Pradesh", "pincode": "452001"}


@pytest.mark.parametrize(
    ("pincode", "valid"),
    [("452001", True), ("45200", False), ("4520011", False), ("052001", False), ("abcdef", False)],
)
def test_pincodes_must_be_six_digits_not_starting_with_zero(pincode, valid):
    errors = FieldErrors()
    validate_address(_Address(line1="x", city="Indore", state="MP", pincode=pincode), errors)
    assert bool(errors) is not valid


def test_a_submitted_state_is_kept_as_typed():
    """Silently rewriting the state would misroute a delivery instead of surfacing it."""
    errors = FieldErrors()
    result = validate_address(_Address(line1="x", city="Nagpur", state="Maharashtra", pincode="440001"), errors)
    assert result["state"] == "Maharashtra"
    assert not errors


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Ravi@TestBakery.IN", "ravi@testbakery.in"),
        ("  ravi@test.co.in  ", "ravi@test.co.in"),
        ("", None),
        (None, None),
    ],
)
def test_valid_and_absent_emails(value, expected):
    errors = FieldErrors()
    assert validate_email(value, errors) == expected
    assert not errors


@pytest.mark.parametrize("value", ["no-at-sign", "two@@at.com", "trailing@dot.", "@nolocal.com", "spaces in@mail.com"])
def test_invalid_emails_are_refused(value):
    errors = FieldErrors()
    assert validate_email(value, errors) is None
    assert [item["field"] for item in errors.fields] == ["email"]


# --- file types ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b"%PDF-1.7 rest", "application/pdf"),
        (b"\xff\xd8\xff\xe0 rest", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n rest", "image/png"),
        (b"MZ\x90\x00", None),
        (b"\x7fELF", None),
        (b"PK\x03\x04", None),
        (b"Rar!\x1a\x07", None),
        (b"<svg xmlns=", None),
        (b'<?xml version="1.0"?>', None),
        (b"#!/bin/sh", None),
        (b"", None),
        (b"ab", None),
    ],
)
def test_the_signature_decides_the_type(head, expected):
    assert detect_content_type(head).content_type == expected


def test_a_refusal_names_what_the_file_looked_like():
    assert "executable" in detect_content_type(b"MZ\x90\x00").reason
    assert "archive" in detect_content_type(b"PK\x03\x04").reason
    assert "SVG" in detect_content_type(b"<svg ").reason


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../../etc/passwd", "passwd"),
        ("C:\\Windows\\system32\\evil.exe", "evil.exe"),
        ("..", "document"),
        ("", "document"),
        ("  spaced name .pdf  ", "spaced name .pdf"),
        ("weird;name|pipe.pdf", "weirdnamepipe.pdf"),
    ],
)
def test_filenames_are_reduced_to_a_display_name(raw, expected):
    assert sanitize_filename(raw) == expected


def test_a_sanitized_name_is_never_long_enough_to_overflow_the_column():
    assert len(sanitize_filename("a" * 500 + ".pdf")) <= 180


@pytest.mark.parametrize(
    ("content_type", "filename", "ok"),
    [
        ("application/pdf", "a.pdf", True),
        ("application/pdf", "a.PDF", True),
        ("application/pdf", "a.exe", False),
        ("image/jpeg", "a.jpeg", True),
        ("image/png", "a.jpg", False),
        ("application/pdf", "noextension", True),
    ],
)
def test_the_extension_is_a_secondary_check_only(content_type, filename, ok):
    assert extension_matches(content_type, filename) is ok


# --- codes and status mapping -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("customer_type", "value", "expected"),
    [
        (CustomerType.RETAIL, 1, "MBGA-R-0001"),
        (CustomerType.INDUSTRIAL, 2, "MBGA-I-0002"),
        (CustomerType.RETAIL, 9999, "MBGA-R-9999"),
        # Past the padding width the code widens rather than wrapping, so it stays unique.
        (CustomerType.RETAIL, 10000, "MBGA-R-10000"),
    ],
)
def test_customer_codes_match_the_specification_format(customer_type, value, expected):
    assert format_code(customer_type, value) == expected


@pytest.mark.parametrize(
    ("backend", "mobile"),
    [
        ("PROFILE_INCOMPLETE", "NEW"),
        ("DOCUMENTS_PENDING", "NEW"),
        ("UNDER_REVIEW", "PENDING"),
        ("APPROVED", "APPROVED"),
        ("REJECTED", "REJECTED"),
        ("SUSPENDED", "SUSPENDED"),
        (None, "NEW"),
    ],
)
def test_account_statuses_map_to_the_mobile_vocabulary(backend, mobile):
    assert to_mobile_account_status(backend) == mobile


def test_clean_text_collapses_internal_whitespace():
    assert clean_text("  Sharma   General   Stores ") == "Sharma General Stores"
    assert clean_text(None) == ""


def test_normalizing_does_not_uppercase_numeric_identifiers():
    assert normalize_document_number(KycDocumentType.AADHAAR, "1234 5678 9012") == "123456789012"
