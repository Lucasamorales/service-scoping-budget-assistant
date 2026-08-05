"""Build the knowledge index artifact from the corpus.

    python -m scripts.build_index                 # keyword-only index
    python -m scripts.build_index --embed         # with Vertex embeddings
    python -m scripts.build_index --out artifacts/index.json

An index without embeddings is a supported mode, not a broken one. Retrieval
works keyword-only on purpose: if it were useless without vectors, the corpus
or the chunking would be wrong. Embeddings blend in when present.

``--embed`` needs ``GCP_PROJECT_ID`` and application-default credentials. A
failed embedding call refuses to publish, because a half-embedded index would
mix vectors with empty slots and silently degrade every dense score.

The build also refuses to overwrite a healthy artifact with a suspiciously
small one. An empty documents folder should not be able to gut production.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import CatalogError
from app.knowledge.catalog import load_catalog
from app.knowledge.chunking import chunk_service_item
from app.knowledge.embeddings import EmbeddingError, build_embedder, with_embeddings
from app.knowledge.index import MIN_CHUNKS_GUARD, EmbeddingContract, KnowledgeIndex
from app.knowledge.manifest import Manifest

DEFAULT_DOCUMENTS_DIR = Path("documents")
DEFAULT_OUTPUT = Path("artifacts/index.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--embed",
        action="store_true",
        help="Embed every chunk via Vertex AI. Requires GCP_PROJECT_ID.",
    )
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

    contract: EmbeddingContract | None = None
    if args.embed:
        settings = get_settings()
        embedder = build_embedder(settings)
        if embedder is None:
            print(
                "Cannot embed: GCP_PROJECT_ID is not set. "
                "Copy .env.example to .env and fill it in, or omit --embed."
            )
            return 1

        print(
            f"Embedding with {embedder.contract.model} "
            f"@ {embedder.contract.dimensions} dimensions..."
        )
        try:
            vectors = embedder.embed_documents([chunk.content for chunk in chunks])
        except EmbeddingError as exc:
            print(f"Embedding failed; refusing to publish a partial index: {exc}")
            return 1

        chunks = list(with_embeddings(chunks, vectors))
        contract = embedder.contract
        print(f"Embedded {len(chunks)} chunks.")

    index = KnowledgeIndex.build(chunks, contract=contract)
    index.write(args.out)

    size_kb = args.out.stat().st_size / 1024
    print(f"Wrote {args.out} ({size_kb:.0f} KB, build {index.build_id}).")
    if contract is None:
        print("No embeddings: retrieval will run keyword-only.")
    else:
        print(f"Embeddings: {contract.model} @ {contract.dimensions}d.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
