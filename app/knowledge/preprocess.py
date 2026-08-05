"""Text repair applied before chunking.

Deliberately small. ``python -m scripts.report_corpus`` shows today's corpus is
clean: no mojibake, no backslash escapes, no empty headings, and only two
non-ASCII characters in 136,000. Nothing here currently changes a single
service document.

It exists anyway because the documents still to arrive - the branch glossary,
the responsible-people directory and the business logic rules - will be written
by people in Google Docs and exported, and that export reliably produces every
defect handled below.

The reason to fix these at ingest rather than at query time is that damage is
retrieval-visible: a chunk containing a broken apostrophe silently fails a
keyword match on the word it belongs to, and nothing in the logs says so.
"""

from __future__ import annotations

import re

__all__ = [
    "normalize_markdown",
    "preprocess",
    "repair_encoding",
    "split_at_sentence_boundary",
]

# UTF-8 read as Latin-1 somewhere upstream. Ordered longest-first so the
# three-byte sequences are consumed before their two-byte prefixes.
_MOJIBAKE = (
    ("\u00e2\u0080\u0099", "\u2019"),
    ("\u00e2\u0080\u009c", "\u201c"),
    ("\u00e2\u0080\u009d", "\u201d"),
    ("\u00e2\u0080\u0094", "\u2014"),
    ("\u00e2\u0080\u0093", "\u2013"),
    ("\u00e2\u0080\u00a6", "\u2026"),
    ("\u00c3\u00a9", "\u00e9"),
    ("\u00c3\u00a8", "\u00e8"),
    ("\u00c3\u00b1", "\u00f1"),
    ("\u00c2\u00a3", "\u00a3"),
    ("\u00c2\u00a0", " "),
)

_EMPTY_HEADING_RE = re.compile(r"^#{1,6}[ \t]*$\n?", re.MULTILINE)
_ESCAPED_PUNCTUATION_RE = re.compile(r"\\([.\-*_>\[\]()#+!])")
_EXCESS_BLANK_LINES_RE = re.compile(r"\n{4,}")
_TRAILING_SPACE_RE = re.compile(r"[ \t]+$", re.MULTILINE)

# Splits after sentence-ending punctuation followed by whitespace. Crude by
# design: a heavier sentence tokeniser is not worth a dependency here, and the
# failure mode of an occasional bad split is a slightly awkward chunk boundary.
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


def repair_encoding(text: str) -> str:
    """Undo the common UTF-8-as-Latin-1 corruptions."""
    for broken, correct in _MOJIBAKE:
        text = text.replace(broken, correct)
    return text


def normalize_markdown(text: str) -> str:
    """Undo the structural damage Google Docs markdown exports introduce."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _EMPTY_HEADING_RE.sub("", text)
    text = _ESCAPED_PUNCTUATION_RE.sub(r"\1", text)
    text = _TRAILING_SPACE_RE.sub("", text)
    text = _EXCESS_BLANK_LINES_RE.sub("\n\n\n", text)
    return text.strip()


def preprocess(text: str) -> str:
    """The full pipeline, applied to every document before chunking."""
    return normalize_markdown(repair_encoding(text))


def split_at_sentence_boundary(
    text: str, *, max_chars: int, overlap: int = 0
) -> tuple[str, ...]:
    """Split oversized text into pieces without ever cutting mid-sentence.

    Returns a single piece when the text already fits, which is the case for
    every service document in the corpus today. Sentences longer than
    ``max_chars`` are emitted whole rather than truncated: an over-long chunk
    is recoverable, a chunk missing its ending is not.
    """
    if len(text) <= max_chars:
        return (text,)

    pieces: list[str] = []
    current = ""

    for sentence in _SENTENCE_BOUNDARY_RE.split(text):
        if not sentence:
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            pieces.append(current)
            tail = current[-overlap:] if overlap else ""
            current = f"{tail} {sentence}".strip() if tail else sentence
        else:
            pieces.append(sentence)
            current = ""

    if current:
        pieces.append(current)
    return tuple(pieces)
