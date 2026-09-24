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

ALLOWED_CONTENT_TYPES = {PDF, JPEG, PNG}
EXTENSIONS: dict[str, set[str]] = {
    PDF: {".pdf"},
    JPEG: {".jpg", ".jpeg"},
    PNG: {".png"},
}

# Enough bytes to cover every signature below.
SNIFF_BYTES = 16


@dataclass(frozen=True)
class Detection:
    content_type: str | None
    reason: str | None = None


def detect_content_type(head: bytes) -> Detection:
    """Identify an allowed format, or explain why the bytes are refused."""
    if len(head) < 4:
        return Detection(None, "The file is empty or too small to identify.")
    if head.startswith(b"%PDF-"):
        return Detection(PDF)
    if head.startswith(b"\xff\xd8\xff"):
        return Detection(JPEG)
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return Detection(PNG)
    return Detection(None, _refusal(head))


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
