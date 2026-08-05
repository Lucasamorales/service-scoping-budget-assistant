"""Show what the chunker produces, with no API calls and no writes.

Runs the exact same chunking the index build runs. Most chunking bugs are
obvious the moment you read a chunk and invisible in any metric, so read twenty
with your own eyes before paying to embed anything.

    python -m scripts.preview_chunks
    python -m scripts.preview_chunks --show 5 --full
    python -m scripts.preview_chunks --source photography--billboards.md
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from app.core.errors import CatalogError
from app.core.types import Chunk, DocType
from app.knowledge.catalog import load_catalog
from app.knowledge.chunking import SERVICE_ITEM_MAX_CHARS, chunk_service_item
from app.knowledge.manifest import Manifest

DEFAULT_DOCUMENTS_DIR = Path("documents")
PREVIEW_CHARS = 400


def build_all_chunks(documents_dir: Path) -> tuple[list[Chunk], list[str]]:
    """Chunk every declared document. Returns the chunks and any notes."""
    manifest = Manifest.load(documents_dir)
    result = load_catalog(manifest)
    notes = [str(issue) for issue in result.errors]

    chunks: list[Chunk] = []
    for item in result.catalog:
        chunks.extend(chunk_service_item(item))

    unsupported = [
        entry.file
        for entry in manifest
        if entry.doc_type is not DocType.SERVICE_ITEM and not entry.doc_type.excluded_from_retrieval
    ]
    if unsupported:
        notes.append(
            f"{len(unsupported)} non-service document(s) declared but not yet chunked here: "
            f"{', '.join(unsupported)}"
        )
    return chunks, notes


def _print_summary(chunks: list[Chunk]) -> None:
    sizes = sorted(len(chunk.content) for chunk in chunks)
    per_source = Counter(chunk.source for chunk in chunks)
    split = {source: count for source, count in per_source.items() if count > 1}

    print(f"{len(chunks)} chunks from {len(per_source)} documents")
    print(
        f"  size: min {sizes[0]}, median {sizes[len(sizes) // 2]}, "
        f"max {sizes[-1]}, total {sum(sizes)}"
    )
    print(f"  rough embedding cost: ~{sum(sizes) // 4} tokens for a full rebuild")

    by_type = Counter(chunk.doc_type.value for chunk in chunks)
    print(f"  by type: {', '.join(f'{name} {count}' for name, count in sorted(by_type.items()))}")

    if split:
        print(f"\n  {len(split)} document(s) split into multiple chunks:")
        for source, count in sorted(split.items()):
            print(f"    {count} chunks  {source}")
    else:
        print("\n  Every document fits in a single chunk, so no verdict is separated")
        print("  from the text it governs.")

    oversized = [chunk for chunk in chunks if len(chunk.content) > SERVICE_ITEM_MAX_CHARS]
    if oversized:
        print(f"\n  WARNING: {len(oversized)} chunk(s) exceed {SERVICE_ITEM_MAX_CHARS} characters")

    missing_hint = [chunk for chunk in chunks if chunk.doc_type is DocType.SERVICE_ITEM
                    and not chunk.use_when]
    if missing_hint:
        print(f"\n  WARNING: {len(missing_hint)} service chunk(s) carry no 'Use when' hints")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS_DIR)
    parser.add_argument("--show", type=int, default=3, help="How many chunks to print.")
    parser.add_argument("--full", action="store_true", help="Print whole chunks, not previews.")
    parser.add_argument("--source", help="Only show chunks from this filename.")
    args = parser.parse_args()

    try:
        chunks, notes = build_all_chunks(args.documents)
    except CatalogError as exc:
        print(f"Could not load the corpus: {exc}")
        return 1

    if not chunks:
        print("No chunks produced.")
        return 1

    _print_summary(chunks)

    for note in notes:
        print(f"\n  NOTE: {note}")

    selected = [c for c in chunks if c.source == args.source] if args.source else chunks
    if args.source and not selected:
        print(f"\nNo chunks from {args.source}")
        return 1

    shown = selected if args.source else selected[: args.show]
    print(f"\n{'=' * 78}")
    for chunk in shown:
        body = chunk.content if args.full else chunk.content[:PREVIEW_CHARS]
        truncated = "" if args.full or len(chunk.content) <= PREVIEW_CHARS else "\n    [...]"
        print(f"\n{chunk.chunk_id}  ({len(chunk.content)} chars, item_id={chunk.item_id})")
        print("-" * 78)
        print(body + truncated)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
