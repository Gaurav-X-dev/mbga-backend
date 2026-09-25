"""Content-type detection from the bytes themselves.

The three things a client tells us about an upload — filename, extension and
``Content-Type`` header — are all attacker-controlled, so none of them decides what a file
is. The leading bytes do. The declared values are checked only for *agreement* with the
signature, which catches an honest mistake and refuses a deliberate spoof.
"""

from dataclasses import dataclass

# Accepted KYC upload formats (spec §17.1).
PDF = "application/pdf"
JPEG = "image/jpeg"
PNG = "image/png"

# Office formats, accepted only for task attachments. A KYC slot still takes PDF/JPG/PNG alone:
# widening that would let an Aadhaar slot hold a spreadsheet.
DOC = "application/msword"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLS = "application/vnd.ms-excel"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV = "text/csv"

ALLOWED_CONTENT_TYPES = {PDF, JPEG, PNG}
#: What a task attachment may be: the KYC set plus the office formats above.
TASK_CONTENT_TYPES = ALLOWED_CONTENT_TYPES | {DOC, DOCX, XLS, XLSX, CSV}

EXTENSIONS: dict[str, set[str]] = {
    PDF: {".pdf"},
    JPEG: {".jpg", ".jpeg"},
    PNG: {".png"},
    DOC: {".doc"},
    DOCX: {".docx"},
    XLS: {".xls"},
    XLSX: {".xlsx"},
    CSV: {".csv", ".txt"},
}

# Enough bytes to cover every signature below. The OLE2 header used by .doc/.xls is 8 bytes.
SNIFF_BYTES = 16


@dataclass(frozen=True)
class Detection:
    content_type: str | None
    reason: str | None = None


def detect_content_type(head: bytes, filename: str | None = None) -> Detection:
    """Identify an allowed format, or explain why the bytes are refused.

    `filename` is consulted for the two formats whose bytes are genuinely ambiguous - a modern
    Office file is a ZIP, and a CSV is plain text - and for nothing else. Everything with a real
    signature is identified by it, because that is the only field an attacker does not control.
    """
    if len(head) < 4:
        return Detection(None, "The file is empty or too small to identify.")
    if head.startswith(b"%PDF-"):
        return Detection(PDF)
    if head.startswith(b"\xff\xd8\xff"):
        return Detection(JPEG)
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return Detection(PNG)
    # OLE2 compound file: the legacy .doc and .xls container. One signature, two formats, so the
    # extension picks between them - both are accepted for the same callers anyway.
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return Detection(XLS if _suffix(filename) == ".xls" else DOC)
    # DOCX and XLSX are ZIP archives. The archive signature alone is refused below, so these are
    # only reachable when the extension says which one it is - and the caller still has to be
    # allowed office formats at all.
    if head.startswith(b"PK\x03\x04"):
        suffix = _suffix(filename)
        if suffix == ".docx":
            return Detection(DOCX)
        if suffix == ".xlsx":
            return Detection(XLSX)
    if _looks_like_text(head) and _suffix(filename) in {".csv", ".txt"}:
        return Detection(CSV)
    return Detection(None, _refusal(head))


def _suffix(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    return filename[filename.rfind(".") :].lower()


def _looks_like_text(head: bytes) -> bool:
    """No NUL bytes and decodable as UTF-8. Enough to tell a spreadsheet export from a binary."""
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _refusal(head: bytes) -> str:
    """Name the dangerous formats explicitly; a precise message is easier to act on.

    These are all things that render or execute somewhere in the chain — an SVG runs script
    in a browser, an archive or executable runs on a reviewer's machine — which is why they
    are called out rather than lumped into one generic rejection.
    """
    dangerous = {
        b"MZ": "a Windows executable",
        b"\x7fELF": "a Linux executable",
        b"PK\x03\x04": "an archive",
        b"Rar!": "an archive",
        b"\x1f\x8b": "an archive",
        b"#!": "a script",
    }
    for signature, label in dangerous.items():
        if head.startswith(signature):
            return f"This looks like {label}. Upload a PDF, JPG or PNG."
    stripped = head.lstrip()[:5].lower()
    if stripped.startswith((b"<?xml", b"<svg")):
        return "SVG and XML files are not accepted. Upload a PDF, JPG or PNG."
    return "Unsupported file type. Upload a PDF, JPG or PNG."


def extension_matches(content_type: str, filename: str | None) -> bool:
    """A secondary check only. A missing extension is accepted; a contradicting one is not."""
    if not filename or "." not in filename:
        return True
    suffix = filename[filename.rfind(".") :].lower()
    return suffix in EXTENSIONS.get(content_type, set())


def sanitize_filename(filename: str | None, *, fallback: str = "document") -> str:
    """A display-safe name for metadata. Never used to build a storage path.

    Directory separators and leading dots are removed so the value is inert even if some
    future code path did join it onto a path.
    """
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(character for character in name if character.isalnum() or character in "._- ").strip(" .")
    return (name or fallback)[:180]
