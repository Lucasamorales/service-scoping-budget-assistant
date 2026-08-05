"""Build the knowledge index artifact from the corpus.

    python -m scripts.build_index                 # keyword-only index
    python -m scripts.build_index --out artifacts/index.json

Embeddings are added in a later step; an index without them is a supported
mode, not a broken one. Retrieval works keyword-only, which is deliberate: if
it were useless without vectors, the corpus or the chunking would be wrong.

The build refuses to overwrite a healthy artifact with a suspiciously small
one. An empty documents folder should not be able to gut production.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.core.errors import CatalogError
from app.knowledge.catalog import load_catalog
from app.knowledge.chunking import chunk_service_item
from app.knowledge.index import MIN_CHUNKS_GUARD, KnowledgeIndex
from app.knowledge.manifest import Manifest

DEFAULT_DOCUMENTS_DIR = Path("documents")
DEFAULT_OUTPUT = Path("artifacts/index.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--allow-small",
        action="store_true",
        help=f"Publish even with fewer than {MIN_CHUNKS_GUARD} chunks.",
    )
    args = parser.parse_args()

    try:
        manifest = Manifest.load(args.documents)
        result = load_catalog(manifest)
    except CatalogError as exc:
        print(f"Could not load the corpus: {exc}")
        return 1

    if result.errors:
        print(f"Refusing to build: the corpus has {len(result.errors)} error(s).")
        for issue in result.errors:
            print(f"  {issue.source}: {issue.message}")
        print("Run `python -m scripts.validate_catalog` for the full report.")
        return 1

    chunks = [chunk for item in result.catalog for chunk in chunk_service_item(item)]
    print(f"Chunked {len(result.catalog)} service items into {len(chunks)} chunks.")

    if len(chunks) < MIN_CHUNKS_GUARD and not args.allow_small:
        print(
            f"\nRefusing to publish {len(chunks)} chunks; the guard is {MIN_CHUNKS_GUARD}. "
            f"This usually means documents went missing. Pass --allow-small if it is intended."
        )
        return 1

    index = KnowledgeIndex.build(chunks)
    index.write(args.out)

    size_kb = args.out.stat().st_size / 1024
    print(f"Wrote {args.out} ({size_kb:.0f} KB, build {index.build_id}).")
    print("No embeddings yet: retrieval will run keyword-only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
