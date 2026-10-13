"""What may be stored as somebody's name.

A customer registered as

    @@@@@@####@@@@@@@@@@@@@@@@@@@@@@@@@@@#₹₹₹₹₹₹₹₹₹__&-+((8889000433456778899((+;;

and nothing stopped it: the field was `max_length=160` and no more. A name is not a label on
one screen - it is copied onto the order, the delivery slip, the invoice, the customer's
notification and, since movements carry one, the stock ledger. By the time it was noticed it
had been written into every one of them, and no amount of cleaning the profile reaches back.

The rules are deliberately loose, because Indian names are: `M/s R.K. Traders`,
`Sharma & Sons`, `A1 Gas Agency`, `D'Souza`, and names in any script at all. What is refused
is a string that is not a name in any language - no letter anywhere in it, or so much
punctuation that the letters are decoration.
"""

import re
import unicodedata

MIN_LENGTH = 2
#: Letters and digits must be at least this share of the non-space characters. A name is
#: allowed its initials, ampersands and apostrophes; it is not allowed to be mostly those.
MIN_ALNUM_SHARE = 0.5

_WHITESPACE = re.compile(r"\s+")
#: Anything in the Unicode "Other" categories - control codes, surrogates, unassigned points.
#: None of them belong in a name, and several render as nothing at all, so a name made of them
#: would read as blank on every screen while passing a length check.
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Cn"})


def tidy(value: str | None) -> str:
    """Trim, collapse runs of whitespace, and drop characters that render as nothing.

    Whitespace is flattened **first**. A newline is a control character, so dropping the
    control characters ahead of this would close the gap it was holding and weld the two
    words of a name typed across two lines into one - on every invoice that name reaches.
    """
    text = _WHITESPACE.sub(" ", value or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) not in _FORBIDDEN_CATEGORIES)
    return _WHITESPACE.sub(" ", text).strip()


def looks_like_a_name(value: str) -> bool:
    """Whether `value` could be somebody's name in some language.

    Not whether it is a *real* name - nothing can tell that - only that it is made of the
    things names are made of. Two tests, both about the whole string rather than a list of
    allowed characters, so no script is shut out:

    1. **At least one letter.** This is what the production case failed: it was punctuation,
       currency signs and a long run of digits, with no letter anywhere in it.
    2. **Letters and digits are at least half of it.** `Ravi@@@@@@@@@@@@@@@@` has a letter but
       is not a name, and a rule that only looked for one letter would admit it.
    """
    stripped = value.replace(" ", "")
    if not stripped:
        return False
    if not any(unicodedata.category(ch).startswith("L") for ch in stripped):
        return False
    alnum = sum(1 for ch in stripped if ch.isalnum())
    return alnum / len(stripped) >= MIN_ALNUM_SHARE


def check_name(value: str | None, *, field: str, required: bool = True) -> str:
    """Tidy `value` and refuse it if it is not a name. Returns what should be stored.

    Raises the module's `ApiError` so the refusal reaches the app as a field error like any
    other, naming the field the form shows.
    """
    # Imported here rather than at module scope: this module is pure text and is imported by
    # schemas that have no business depending on the HTTP layer.
    from fastapi import status as http_status

    from app.shared.exceptions.api_error import ApiError

    def refuse(code: str, message: str) -> ApiError:
        return ApiError(
            "VALIDATION_ERROR",
            http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            fields=[{"field": field, "code": code, "message": message}],
        )

    name = tidy(value)
    if not name:
        if required:
            raise refuse("name_required", "Enter a name.")
        return ""
    if len(name) < MIN_LENGTH:
        raise refuse("name_too_short", f"A name needs at least {MIN_LENGTH} characters.")
    if not looks_like_a_name(name):
        raise refuse("name_invalid", "Enter a real name, not symbols or numbers.")
    return name
