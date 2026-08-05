"""Turning text into vectors, under one contract.

The contract is the load-bearing piece. An index built with one model or
dimensionality and queried with another produces plausible-looking ranks that
are quietly wrong, because cosine distance between vectors from different
spaces is meaningless. :class:`~app.knowledge.index.EmbeddingContract` is
recorded in the artifact and checked at load; this module is the only place
vectors are produced, so the two sides cannot drift apart by accident.

Two further rules:

**Documents and queries use different task types.** Vertex's embedding models
are trained that way: ``RETRIEVAL_DOCUMENT`` for the corpus,
``RETRIEVAL_QUERY`` for the question. Using the same type for both throws away
the optimisation the model was built for.

**Truncated vectors are normalised here.** Asking for 768 dimensions out of a
model whose native size is larger skips the API's own unit-normalisation, so
cosine similarity would then favour longer vectors. Normalising after every
call keeps the maths honest regardless of the requested size.

The SDK is imported inside the client so the rest of the application stays
importable without the ``cloud`` extra.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Literal, Protocol

import structlog

from app.core.config import Settings
from app.core.types import Chunk
from app.knowledge.index import EmbeddingContract

__all__ = [
    "Embedder",
    "EmbeddingError",
    "VertexEmbedder",
    "build_embedder",
    "normalize",
    "with_embeddings",
]

logger = structlog.get_logger(__name__)

TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]

MAX_BATCH_SIZE = 100
"""Vertex's per-request ceiling for ``embed_content``."""

MAX_BATCH_CHARS = 40_000
"""Rough stand-in for a token budget. Characters / 4 ≈ tokens; kept well under
the free-tier per-minute allowance so a rebuild of 81 chunks never paces."""

MAX_ATTEMPTS = 6
INITIAL_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 60.0


class EmbeddingError(RuntimeError):
    """An embedding call failed after retries, or returned the wrong shape."""


def normalize(vector: Sequence[float]) -> tuple[float, ...]:
    """Unit-length the vector. A zero vector is returned unchanged."""
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return tuple(vector)
    return tuple(value / norm for value in vector)


class Embedder(Protocol):
    """Text in, unit vectors out. Build and query share this seam."""

    @property
    def contract(self) -> EmbeddingContract: ...

    def embed_query(self, text: str) -> tuple[float, ...] | None:
        """Embed a search query. ``None`` means degrade to keyword scoring."""
        ...

    def embed_documents(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        """Embed corpus text. Raises on failure: a partial index must not publish."""
        ...


class VertexEmbedder:
    """Gemini embeddings on Vertex AI.

    Connected lazily, same pattern as the chat client: a broken configuration
    costs one attempt, not one per call for the life of the process.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._contract = EmbeddingContract(
            model=settings.vertex_embed_model,
            dimensions=settings.vertex_embed_dimensions,
        )
        self._client: Any | None = None
        self._unavailable: str | None = None

    @property
    def contract(self) -> EmbeddingContract:
        return self._contract

    def embed_query(self, text: str) -> tuple[float, ...] | None:
        if not text.strip():
            return None
        try:
            return self._embed([text], task="RETRIEVAL_QUERY")[0]
        except EmbeddingError as exc:
            # Query-time failure is recoverable: keyword retrieval still works.
            # Remembered so a broken Vertex costs one log line, not one per turn.
            self._unavailable = str(exc)
            logger.warning("embed.query_failed", error=str(exc))
            return None

    def embed_documents(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []
        return self._embed(list(texts), task="RETRIEVAL_DOCUMENT")

    def _connect(self) -> Any:
        if self._client is not None:
            return self._client
        if self._unavailable is not None:
            raise EmbeddingError(self._unavailable)

        try:
            from google import genai
        except ImportError as exc:
            self._unavailable = "google-genai is not installed; install the 'cloud' extra"
            logger.warning("embed.sdk_missing", detail=self._unavailable)
            raise EmbeddingError(self._unavailable) from exc

        try:
            self._client = genai.Client(
                vertexai=True,
                project=self._settings.gcp_project_id,
                location=self._settings.gcp_region,
            )
        except Exception as exc:
            self._unavailable = str(exc)
            logger.error("embed.connect_failed", error=self._unavailable)
            raise EmbeddingError(self._unavailable) from exc

        logger.info(
            "embed.connected",
            model=self._contract.model,
            dimensions=self._contract.dimensions,
            project=self._settings.gcp_project_id,
            region=self._settings.gcp_region,
        )
        return self._client

    def _embed(self, texts: list[str], *, task: TaskType) -> list[tuple[float, ...]]:
        vectors: list[tuple[float, ...]] = []
        for batch in _batches(texts):
            vectors.extend(self._embed_batch(batch, task=task))
        if len(vectors) != len(texts):
            raise EmbeddingError(
                f"Expected {len(texts)} embeddings, received {len(vectors)}."
            )
        return vectors

    def _embed_batch(self, texts: list[str], *, task: TaskType) -> list[tuple[float, ...]]:
        client = self._connect()
        config = {
            "task_type": task,
            "output_dimensionality": self._contract.dimensions,
        }

        delay = INITIAL_BACKOFF_SECONDS
        last_error: Exception | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = client.models.embed_content(
                    model=self._contract.model,
                    contents=texts,
                    config=config,
                )
            except Exception as exc:  # noqa: BLE001 - SDK raises many unrelated types
                # Retried when the error looks transient; otherwise remembered
                # and raised as EmbeddingError below so a partial index never
                # publishes.
                last_error = exc
                if not _is_retryable(exc) or attempt == MAX_ATTEMPTS:
                    break
                logger.warning(
                    "embed.retry",
                    attempt=attempt,
                    wait=delay,
                    error=str(exc),
                )
                time.sleep(delay)
                delay = min(delay * 2, MAX_BACKOFF_SECONDS)
                continue

            embeddings = getattr(response, "embeddings", None) or []
            if len(embeddings) != len(texts):
                raise EmbeddingError(
                    f"Batch of {len(texts)} returned {len(embeddings)} embeddings."
                )

            vectors: list[tuple[float, ...]] = []
            for embedding in embeddings:
                values = getattr(embedding, "values", None)
                if not values:
                    raise EmbeddingError("Embedding response contained an empty vector.")
                if len(values) != self._contract.dimensions:
                    raise EmbeddingError(
                        f"Expected {self._contract.dimensions} dimensions, "
                        f"got {len(values)}. Check VERTEX_EMBED_DIMENSIONS."
                    )
                vectors.append(normalize(values))
            return vectors

        raise EmbeddingError(str(last_error) if last_error else "embedding failed")


def build_embedder(settings: Settings) -> Embedder | None:
    """Return an embedder if Vertex is configured, otherwise ``None``.

    ``None`` is supported: retrieval runs keyword-only, which is how the
    assistant works today and how it keeps working when credentials lapse.
    """
    if not settings.vertex_configured:
        logger.info("embed.not_configured", detail="no GCP project set; keyword-only retrieval")
        return None
    return VertexEmbedder(settings)


def with_embeddings(
    chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
) -> tuple[Chunk, ...]:
    """Attach vectors to chunks, producing a new tuple.

    Chunks are frozen, so embedding is a rebuild rather than a mutation. Kept
    here so the build script and any future re-embed path share one place that
    knows the field name.
    """
    if len(chunks) != len(vectors):
        raise EmbeddingError(
            f"Cannot attach {len(vectors)} vectors to {len(chunks)} chunks."
        )
    return tuple(
        replace(chunk, embedding=tuple(vector))
        for chunk, vector in zip(chunks, vectors, strict=True)
    )


def _batches(texts: Sequence[str]) -> list[list[str]]:
    """Split into request-sized groups without orphaning a long document."""
    batches: list[list[str]] = []
    current: list[str] = []
    size = 0

    for text in texts:
        cost = len(text)
        fits = current and (
            len(current) >= MAX_BATCH_SIZE or size + cost > MAX_BATCH_CHARS
        )
        if fits:
            batches.append(current)
            current, size = [], 0
        current.append(text)
        size += cost

    if current:
        batches.append(current)
    return batches


def _is_retryable(exc: Exception) -> bool:
    text = str(exc).lower()
    name = type(exc).__name__.lower()
    return any(
        marker in text or marker in name
        for marker in ("429", "rate", "quota", "unavailable", "timeout", "503", "500")
    )
