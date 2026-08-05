"""Canonical key and normalisation functions.

Every entity that crosses a module boundary is identified by a key produced
here, and nowhere else. Identity bugs of the ``"Chapter 2"`` versus
``"Chapter 2: title"`` kind are silent: a lookup returns nothing, a counter
stays at zero, and no error is ever logged. One shared implementation is the
only reliable defence.

Two distinct normalisations live here and must not be confused:

``slugify``
    Produces stable identifiers. Punctuation is dropped, so ``"Design &
    creative"`` becomes ``design-creative``. This matches the convention the
    corpus filenames already follow.

``normalize_term``
    Produces text for alias matching. Punctuation becomes meaningful
    whitespace and ``&`` expands to ``and``, so a user typing "design and
    creative" matches an item titled "Design & creative".
"""

from __future__ import annotations

import re
import unicodedata

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
_WHITESPACE = re.compile(r"\s+")

# Brand prefixes carry no information for branch identity, and users drop them
# freely: "Acme Manchester", "Manchester" and "manchester" are one branch.
_BRANCH_BRAND_PREFIXES = ("acme", "i fly")


def strip_accents(text: str) -> str:
    """Fold accented characters onto their ASCII base."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def slugify(text: str) -> str:
    """Reduce arbitrary text to a lowercase hyphenated identifier."""
    folded = strip_accents(text).lower()
    return _NON_ALPHANUMERIC.sub("-", folded).strip("-")


def normalize_term(text: str) -> str:
    """Reduce text to a comparable form for alias and keyword matching."""
    folded = strip_accents(text).lower().replace("&", " and ")
    spaced = _NON_ALPHANUMERIC.sub(" ", folded)
    return _WHITESPACE.sub(" ", spaced).strip()


def tokenize(text: str) -> tuple[str, ...]:
    """Split text into normalised tokens for keyword scoring."""
    normalized = normalize_term(text)
    return tuple(normalized.split()) if normalized else ()


def service_key(section: str, item: str) -> str:
    """Build the canonical identifier for a service catalog entry.

    Derived from the ``Section`` and ``Item`` fields inside the document rather
    than from its filename, because at least one filename in the corpus is
    truncated and no longer reflects the item it contains.
    """
    return f"{slugify(section)}--{slugify(item)}"


def branch_key(text: str) -> str:
    """Build the canonical identifier for a branch.

    The branch glossary is not yet part of the corpus. When it lands it will
    supply the alias table, but every alias will resolve through this function,
    so branch identity stays decided in exactly one place.
    """
    normalized = normalize_term(text)
    for prefix in _BRANCH_BRAND_PREFIXES:
        if normalized.startswith(f"{prefix} "):
            normalized = normalized[len(prefix) :].strip()
            break
    return slugify(normalized)
