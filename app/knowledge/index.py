"""The knowledge index: a JSON artifact built offline, held in memory at runtime.

Sizing decides the design here. The whole corpus is 81 chunks. Searching that
in memory takes well under a millisecond, while a round trip to a managed
vector database costs 30-100ms and adds a dependency that can rate-limit, drop
connections or be down. For a corpus this size the network hop *is* the
latency, and the database is the part that breaks under load. So the index is
a file: built offline, published to Cloud Storage, and loaded into each
container at startup, where it scales horizontally for free.

Two properties are load bearing.

**The embedding contract is recorded in the artifact.** If an index is built
with one model or dimensionality and queried with another, cosine distance is
meaningless and retrieval fails *silently* - plausible-looking chunks, quietly
wrong. :meth:`KnowledgeIndex.verify_contract` turns that into a loud error.

**Loading never throws.** A missing or unreadable index yields an empty one and
the assistant answers from the catalog alone. Retrieval degrading is an
inconvenience; the whole service failing to start is an outage.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from app.core.types import Chunk, DocType

__all__ = [
    "MIN_CHUNKS_GUARD",
    "EmbeddingContract",
    "IndexContractError",
    "KnowledgeIndex",
]

logger = structlog.get_logger(__name__)

INDEX_FORMAT_VERSION = 1

MIN_CHUNKS_GUARD = 60
"""Refuse to publish an index smaller than this.

The corpus produces 81 chunks. A build yielding far fewer means documents went
missing, and publishing it would replace a working knowledge base with a
gutted one. Raise this alongside the corpus as it grows.
"""


class IndexContractError(RuntimeError):
    """An index was built under different embedding settings than the ones in use."""


@dataclass(frozen=True, slots=True)
class EmbeddingContract:
    """The model and dimensionality an index was built with.

    Must be identical at build time and query time. Nothing downstream can
    detect a violation, which is why it is checked here.
    """

    model: str
    dimensions: int

    def as_dict(self) -> dict[str, Any]:
        return {"model": self.model, "dimensions": self.dimensions}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EmbeddingContract:
        return cls(model=str(raw["model"]), dimensions=int(raw["dimensions"]))


def _chunk_to_dict(chunk: Chunk) -> dict[str, Any]:
    record: dict[str, Any] = {
        "chunkId": chunk.chunk_id,
        "content": chunk.content,
        "source": chunk.source,
        "docType": chunk.doc_type.value,
        "chunkIndex": chunk.chunk_index,
    }
    if chunk.item_id:
        record["itemId"] = chunk.item_id
    if chunk.section_title:
        record["sectionTitle"] = chunk.section_title
    if chunk.section:
        record["section"] = chunk.section
    if chunk.use_when:
        record["useWhen"] = list(chunk.use_when)
    if chunk.embedding is not None:
        record["embedding"] = list(chunk.embedding)
    return record


def _chunk_from_dict(record: dict[str, Any]) -> Chunk:
    embedding = record.get("embedding")
    return Chunk(
        chunk_id=record["chunkId"],
        content=record["content"],
        source=record["source"],
        doc_type=DocType(record["docType"]),
        chunk_index=int(record["chunkIndex"]),
        item_id=record.get("itemId"),
        section_title=record.get("sectionTitle"),
        section=record.get("section"),
        use_when=tuple(record.get("useWhen", ())),
        embedding=tuple(float(value) for value in embedding) if embedding else None,
    )


@dataclass(frozen=True, slots=True)
class KnowledgeIndex:
    """Every retrievable chunk, plus the provenance of the build that made it."""

    chunks: tuple[Chunk, ...] = ()
    build_id: str = ""
    contract: EmbeddingContract | None = None
    """``None`` means the index carries no embeddings and retrieval is
    keyword-only. That is a supported mode, not a broken one."""

    def __len__(self) -> int:
        return len(self.chunks)

    def __iter__(self) -> Iterator[Chunk]:
        return iter(self.chunks)

    @property
    def is_empty(self) -> bool:
        return not self.chunks

    @property
    def has_embeddings(self) -> bool:
        return any(chunk.embedding is not None for chunk in self.chunks)

    def retrievable(self) -> tuple[Chunk, ...]:
        """Chunks eligible to be returned as evidence."""
        return tuple(chunk for chunk in self.chunks if not chunk.doc_type.excluded_from_retrieval)

    def verify_contract(self, expected: EmbeddingContract) -> None:
        """Fail loudly if this index was built under different embedding settings."""
        if not self.has_embeddings:
            return
        if self.contract is None:
            raise IndexContractError(
                "Index carries embeddings but records no embedding contract. "
                "Rebuild it with `python -m scripts.build_index`."
            )
        if self.contract != expected:
            raise IndexContractError(
                f"Index was built with {self.contract.model} at "
                f"{self.contract.dimensions} dimensions, but this process is configured for "
                f"{expected.model} at {expected.dimensions}. Cosine distance between vectors "
                f"from different models is meaningless, so retrieval would fail silently. "
                f"Rebuild the index or restore the original settings."
            )

    @classmethod
    def build(
        cls, chunks: Sequence[Chunk], *, contract: EmbeddingContract | None = None
    ) -> KnowledgeIndex:
        return cls(
            chunks=tuple(chunks),
            build_id=datetime.now(UTC).isoformat(timespec="seconds"),
            contract=contract,
        )

    def to_json(self) -> str:
        payload = {
            "formatVersion": INDEX_FORMAT_VERSION,
            "buildId": self.build_id,
            "embedding": self.contract.as_dict() if self.contract else None,
            "chunks": [_chunk_to_dict(chunk) for chunk in self.chunks],
        }
        return json.dumps(payload, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> KnowledgeIndex:
        payload = json.loads(raw)

        version = payload.get("formatVersion")
        if version != INDEX_FORMAT_VERSION:
            raise IndexContractError(
                f"Index format version {version} is not the expected "
                f"{INDEX_FORMAT_VERSION}. Rebuild the index."
            )

        embedding = payload.get("embedding")
        return cls(
            chunks=tuple(_chunk_from_dict(record) for record in payload.get("chunks", [])),
            build_id=str(payload.get("buildId", "")),
            contract=EmbeddingContract.from_dict(embedding) if embedding else None,
        )

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load_local(cls, path: Path) -> KnowledgeIndex:
        """Read an index from disk, returning an empty one on any failure.

        Deliberately total. The assistant still answers scope questions from
        the catalog with no index at all, so a bad artifact should degrade
        retrieval rather than prevent the service starting.
        """
        try:
            index = cls.from_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.warning("index.missing", path=str(path))
            return cls()
        except (OSError, ValueError, KeyError, IndexContractError) as exc:
            logger.error("index.unreadable", path=str(path), error=str(exc))
            return cls()

        logger.info(
            "index.loaded",
            path=str(path),
            chunks=len(index),
            build_id=index.build_id,
            embeddings=index.has_embeddings,
        )
        return index
