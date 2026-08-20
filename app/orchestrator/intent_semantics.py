"""Semantic intent helpers — paraphrase without growing phrase lists.

Inventory questions ("give me a list of services", "what do you cover?") must
hit the full catalog tool, not top-k RAG retrieval. Retrieval cannot list every
service: it only returns a handful of chunks. What we make semantic is
*recognising* that the user wants the inventory; the answer still comes from
``list_services(catalog)``.
"""

from __future__ import annotations

from typing import Protocol

import structlog

from app.knowledge.embeddings import Embedder, normalize

__all__ = ["InventoryIntentDetector"]

logger = structlog.get_logger(__name__)

# Intent anchors, not user-facing regex. New phrasings match by embedding
# similarity to these, not by adding another pattern.
_INVENTORY_EXEMPLARS = (
    "list all the services we offer",
    "what services does central marketing cover",
    "show me the full catalogue of offerings",
    "give me a breakdown of everything in scope",
    "what work can you do for the branches",
    "inventory of on demand versus included services",
)

# Nearby but opposite: asking about one job, not asking for the menu.
_SCOPING_EXEMPLARS = (
    "can we do merch for the new branch",
    "is database clean-up included in scope",
    "do you cover billboard photography",
    "we need a photoshoot next month",
    "is this local or central marketing",
)

# Tuned conservatively — budget questions sat ~0.54 vs inventory; false
# positives stole turns. Prefer high confidence + clear margin over recall.
_DEFAULT_MIN_SCORE = 0.72
_DEFAULT_MARGIN = 0.10


class _QueryEmbedder(Protocol):
    def embed_query(self, text: str) -> tuple[float, ...] | None: ...


class InventoryIntentDetector:
    """True when the message is closer to inventory exemplars than to scoping ones."""

    def __init__(
        self,
        embedder: Embedder | _QueryEmbedder,
        *,
        min_score: float = _DEFAULT_MIN_SCORE,
        margin: float = _DEFAULT_MARGIN,
    ) -> None:
        self._embedder = embedder
        self._min_score = min_score
        self._margin = margin
        self._inventory: tuple[tuple[float, ...], ...] | None = None
        self._scoping: tuple[tuple[float, ...], ...] | None = None
        self._failed = False

    def __call__(self, message: str) -> bool:
        return self.looks_like_inventory(message)

    def looks_like_inventory(self, message: str) -> bool:
        text = (message or "").strip()
        if len(text) < 8:
            return False
        if self._failed:
            return False
        query = self._embedder.embed_query(text)
        if query is None:
            return False
        if not self._ensure_anchors():
            return False

        inv = _best_similarity(query, self._inventory or ())
        scope = _best_similarity(query, self._scoping or ())
        hit = inv >= self._min_score and inv >= scope + self._margin
        logger.info(
            "intent.inventory_semantic",
            hit=hit,
            inventory_score=round(inv, 4),
            scoping_score=round(scope, 4),
        )
        return hit

    def _ensure_anchors(self) -> bool:
        if self._inventory is not None and self._scoping is not None:
            return True
        try:
            inv = tuple(
                vec
                for text in _INVENTORY_EXEMPLARS
                if (vec := self._embedder.embed_query(text)) is not None
            )
            scope = tuple(
                vec
                for text in _SCOPING_EXEMPLARS
                if (vec := self._embedder.embed_query(text)) is not None
            )
        except Exception as exc:  # noqa: BLE001 - detector disables itself, regex path remains
            self._failed = True
            logger.warning("intent.inventory_anchors_failed", error=str(exc))
            return False
        if not inv or not scope:
            self._failed = True
            return False
        self._inventory = inv
        self._scoping = scope
        return True


def _best_similarity(query: tuple[float, ...], anchors: tuple[tuple[float, ...], ...]) -> float:
    if not anchors:
        return 0.0
    q = normalize(query)
    return max(_dot(q, normalize(anchor)) for anchor in anchors)


def _dot(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    n = min(len(left), len(right))
    return sum(left[i] * right[i] for i in range(n))
