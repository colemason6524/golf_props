"""Conservative event-name equivalence, separate from price eligibility.

No sponsor words are removed and no fuzzy edit-distance match is accepted.
Initialisms are candidates only: callers must corroborate date and field.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional


def event_name_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return re.sub(r"[^a-z0-9]+", "", text)


def _tokens(value: object) -> list[str]:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    # Dotted initialisms and typographic punctuation are formatting variants.
    text = re.sub(r"\b(?:[a-z]\.){2,}[a-z]?\.?", lambda m: m[0].replace(".", ""), text)
    return re.findall(r"[a-z0-9]+", text)


def event_name_match(left: object, right: object) -> Optional[str]:
    """Return exact/initialism, or None. Initialisms need external evidence.

    Allow one token to expand to >=3 consecutive words, preserving at least one
    full word on either side of that span (WWT Championship, not just WWT).
    Two-word initials and dropped sponsor/location/format words never match.
    """
    if event_name_key(left) and event_name_key(left) == event_name_key(right):
        return "exact"
    a, b = _tokens(left), _tokens(right)
    for short, long in ((a, b), (b, a)):
        extra = len(long) - len(short)
        if extra < 2 or len(short) < 2:
            continue
        for index, token in enumerate(short):
            span = long[index:index + extra + 1]
            if (
                token.isalpha()
                and len(token) >= 3
                and token == "".join(word[0] for word in span)
                and short[:index] == long[:index]
                and short[index + 1:] == long[index + extra + 1:]
            ):
                return "initialism"
    return None
