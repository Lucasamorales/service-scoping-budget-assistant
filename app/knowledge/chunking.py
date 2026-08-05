"""Turning documents into retrievable chunks, one strategy per document type.

The question worth asking of each document type is: *what is the smallest piece
of this that is still true?* Chunk to that.

For a service item the answer is the whole document. Every one of the 81 fits
in about 1,700 characters, and a fragment describing what billboards are
without the verdict attached is not merely incomplete - it invites the model to
supply a verdict of its own. So a service item is one chunk, opening with a
header that names its section, item, status and aliases, and if one ever grows
large enough to need splitting, that header is repeated on every piece. The
verdict is never orphaned from the text it governs.

Reference documents that have not arrived yet - glossary, directory, business
logic - are chunked per heading instead, because those genuinely are lists of
independent entries.
"""

from __future__ import annotations

import re

from app.core.types import Chunk, DocType, ServiceItem
from app.knowledge.preprocess import preprocess, split_at_sentence_boundary

__all__ = [
    "SERVICE_ITEM_MAX_CHARS",
    "chunk_reference_document",
    "chunk_service_item",
]

SERVICE_ITEM_MAX_CHARS = 3000
"""Generous headroom over the 2,030-character largest document in the corpus.
Exceeding it is not an error, but it means a document has grown unlike its
peers and the split behaviour below is worth checking by eye."""

REFERENCE_MAX_CHARS = 1400
REFERENCE_OVERLAP = 160
MIN_CHUNK_CHARS = 80
"""Below this a chunk is a fragment, not a unit of meaning."""

_FIRST_SECTION_RE = re.compile(r"^##[ \t]", re.MULTILINE)
_SECTION_SPLIT_RE = re.compile(r"^##[ \t]+(?P<title>.+?)[ \t]*$", re.MULTILINE)


def _body_after_header_block(text: str) -> str:
    """Drop the H1 and the ``**Field:**`` block, keeping the ``##`` sections.

    Those fields are exactly what the generated chunk header re-states, in a
    form that reads better in a prompt. Keeping both would spend tokens saying
    the same thing twice.
    """
    match = _FIRST_SECTION_RE.search(text)
    return text[match.start() :].strip() if match else text.strip()


def build_service_item_header(item: ServiceItem) -> str:
    """The self-describing preamble carried inside a service item chunk.

    Provenance lives in the text, not only in metadata, for two reasons: the
    model can cite it accurately without a separate instruction explaining what
    it is reading, and ``Use when`` is a retrieval hint written by someone who
    knows the domain, so it participates in keyword scoring for free.
    """
    lines = [
        f"[{item.section} \u2014 {item.item}]",
        f"Status: {item.status_raw.strip()} \u2014 {item.status_meaning}",
    ]
    if item.aliases:
        lines.append(f"Use when: {', '.join(item.aliases)}")
    return "\n".join(lines)


def chunk_service_item(item: ServiceItem) -> tuple[Chunk, ...]:
    """Chunk one service item, normally into exactly one chunk."""
    header = build_service_item_header(item)
    body = _body_after_header_block(preprocess(item.body))

    budget = SERVICE_ITEM_MAX_CHARS - len(header) - 2
    pieces = split_at_sentence_boundary(body, max_chars=budget, overlap=REFERENCE_OVERLAP)

    return tuple(
        Chunk(
            chunk_id=f"{item.source}:{index}",
            content=f"{header}\n\n{piece}",
            source=item.source,
            doc_type=DocType.SERVICE_ITEM,
            chunk_index=index,
            item_id=item.item_id,
            section_title=item.item,
            section=item.section,
            use_when=item.aliases,
        )
        for index, piece in enumerate(pieces)
    )


def chunk_reference_document(text: str, source: str, doc_type: DocType) -> tuple[Chunk, ...]:
    """Chunk a glossary, directory or business logic document by heading.

    Meta documents return nothing: they belong in the always-on prompt, and a
    document that is both instruction and evidence lets the assistant cite its
    own instructions back as proof.
    """
    if doc_type.excluded_from_retrieval:
        return ()

    cleaned = preprocess(text)
    chunks: list[Chunk] = []

    for title, body in _split_by_heading(cleaned):
        label = f"[{source} \u2014 {title}]" if title else f"[{source}]"
        budget = REFERENCE_MAX_CHARS - len(label) - 2
        for piece in split_at_sentence_boundary(
            body, max_chars=budget, overlap=REFERENCE_OVERLAP
        ):
            if len(piece) < MIN_CHUNK_CHARS:
                continue
            chunks.append(
                Chunk(
                    chunk_id=f"{source}:{len(chunks)}",
                    content=f"{label}\n\n{piece}",
                    source=source,
                    doc_type=doc_type,
                    chunk_index=len(chunks),
                    section_title=title,
                )
            )

    return tuple(chunks)


def _split_by_heading(text: str) -> list[tuple[str | None, str]]:
    """Split into ``(heading, body)`` pairs, preserving any preamble."""
    matches = list(_SECTION_SPLIT_RE.finditer(text))
    if not matches:
        return [(None, text)] if text.strip() else []

    sections: list[tuple[str | None, str]] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append((None, preamble))

    for index, match in enumerate(matches):
        start = match.end()
        finish = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:finish].strip()
        if body:
            sections.append((match.group("title"), body))

    return sections
