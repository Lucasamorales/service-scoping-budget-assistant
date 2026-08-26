"""Retrieval over the in-memory index.

Built keyword-first on purpose. If retrieval is useless without vectors, the
corpus or the chunking is wrong, and you want to discover that before paying
to embed anything. Embeddings are added later and blend in; they never become
a hard dependency, and a failure to embed mid-request degrades to keyword
within the same turn rather than failing it.

Two behaviours matter more than the scoring formula:

**Force-include beats scoring.** When the resolver has already identified the
service being asked about, that item's chunk is placed in the pack directly.
Similarity is not consulted, because a job cannot be done without the slice it
is about, and a score is a hope rather than a guarantee.

**Every result explains itself.** :class:`RetrievalResult` carries a ``mode``
string and each hit carries the terms that matched. When an answer is wrong,
this is what tells you it retrieved the wrong thing, usually before you open a
log.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Protocol

import structlog

from app.core.keys import content_tokens
from app.core.types import Chunk, DocType
from app.knowledge.index import KnowledgeIndex

__all__ = ["InMemoryRetriever", "RetrievalResult", "Retriever", "ScoredChunk"]

logger = structlog.get_logger(__name__)

HINT_WEIGHT = 3.0
"""Weight for a term appearing in an item's name or its ``Also known as`` line.
Those phrases were written by someone who knows the domain, which makes them a
far stronger signal than the same word buried in prose."""

SECTION_WEIGHT = 1.5
"""Weight for a term matching the catalog section. Above body text, below the
item itself, so naming a section narrows the field without ever letting
"Photography" outrank the specific photography item being asked about."""

BODY_WEIGHT = 1.0

BIGRAM_HINT_WEIGHT = 2.0
BIGRAM_BODY_WEIGHT = 0.75
"""Adjacent word pairs score above single words: 'photo booth' appearing
together means something that 'photo' and 'booth' scattered apart does not.

Both are multiplied by the rarity of the words involved, exactly as single
terms are. When these were flat additions a common pair like 'web page'
outweighed every other signal in the query and buried the item actually being
asked about."""

NAME_COVERAGE_WEIGHT = 3.0
"""Reward for a query accounting for most of an item's own name or one of its
aliases. Token overlap alone treats 'marketing calendar' as two lucky hits;
coverage recognises that it is the entire identity of the item called
Marketing calendars, which is a far stronger claim."""

DENSE_WEIGHT = 0.75
KEYWORD_WEIGHT = 0.25
"""Keyword keeps a quarter of the blend even with embeddings present. Exact
tokens carry real weight in this domain: product names like POS, GA4 and
Supermetrics either appear or they do not."""

DENSE_CONFIDENCE_WEIGHT = 0.5
KEYWORD_CONFIDENCE_WEIGHT = 0.5
"""How the two halves combine into a *confidence*, as opposed to a score.

Deliberately not the weights above, because the two numbers answer different
questions. Ranking asks which of these items fits best, and there similarity
deserves the larger say. Confidence asks whether this item is worth acting on
at all — and there, letting a mediocre cosine outvote an unmistakable lexical
match is simply wrong. "Can we get a wrap-up on how the Heart Radio campaign
performed?" names Campaign wrap-ups almost word for word, covering 82% of its
identity, while scoring only 0.62 cosine; under a 0.75/0.25 confidence blend
that landed at 0.494 and was discarded as not worth acting on.

Measured over the 49 eval prompts that name an expected item, against all 89
items: at a threshold of 0.5 the 0.75/0.25 blend keeps 48 of 49 expected items
and admits 2.9% of the rest, while an even blend keeps 49 of 49 and admits
2.7%. Strictly better on both counts, which is rare enough to be worth
recording."""

MIN_SCORE = 0.05
"""Below this a hit is noise. Returning nothing is better than returning
something irrelevant, which is what pushes a model into inventing an answer."""

KEYWORD_HALF_CONFIDENCE = 1.6
"""The keyword score that reads as an even chance: ``score / (score + this)``
is 0.5 here, rises towards 1 and never reaches it.

Set to the value the resolver's old absolute floor used, so that in
keyword-only mode ``confidence >= 0.5`` and ``score >= 1.6`` accept exactly the
same hits. Introducing a scale is not an excuse to change behaviour while
nobody is looking."""

DENSE_FLOOR = 0.55
DENSE_CEILING = 0.77
"""Cosines that read as no evidence and as certainty.

Raw cosine is not a confidence and using it as one would be badly wrong.
Measured over the 25 retrieval prompts against all 89 items with
``gemini-embedding-001`` at 768 dimensions, the expected item scores 0.650 to
0.794 (median 0.730) while every other item scores 0.479 to 0.740 (median
0.570, p95 0.641). An unrelated service sits at 0.57 — which as a "confidence"
would read as 57% sure.

The classes overlap only between 0.641 and 0.673, so the boundary is about
0.657, and these anchors put that at roughly 0.5. Rescaling makes the dense and
keyword halves comparable numbers, which is the whole point: blending two
signals on different scales is how a threshold silently changes meaning.

**These are specific to this model and this corpus.** The index records its
embedding contract; re-derive them if either changes."""


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    chunk: Chunk
    score: float
    matched: tuple[str, ...] = ()
    """The query terms this chunk actually contains. Kept free of derived
    signals so callers can compare two hits and see which one the query
    genuinely distinguishes."""

    coverage: float = 0.0
    """How much of the item's own name the query accounted for."""

    confidence: float = 0.0
    """How much this hit is worth acting on, from 0 to 1.

    Distinct from ``score``, and the distinction matters. ``score`` ranks hits
    against each other within one query; it is a sum of weights whose size
    depends on the query and on whether embeddings are in the blend, so the
    same number means different things in different modes. ``confidence``
    answers the other question - is this good enough to act on at all - and
    means the same thing everywhere, which is what an absolute threshold needs
    in order to keep its meaning when the retrieval mode changes."""

    forced: bool = False
    """True when the resolver required this slice rather than the score earning it."""


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """What retrieval returned, and how."""

    hits: tuple[ScoredChunk, ...] = ()
    mode: str = "empty"
    """How this was retrieved: ``keyword``, ``keyword+dense``, ``forced-only``
    or ``empty``. Always surfaced, so 'why did it say that?' has an answer."""

    notes: tuple[str, ...] = field(default=())

    def __len__(self) -> int:
        return len(self.hits)

    def __bool__(self) -> bool:
        return bool(self.hits)

    @property
    def chunks(self) -> tuple[Chunk, ...]:
        return tuple(hit.chunk for hit in self.hits)

    @property
    def item_ids(self) -> tuple[str, ...]:
        seen: list[str] = []
        for hit in self.hits:
            if hit.chunk.item_id and hit.chunk.item_id not in seen:
                seen.append(hit.chunk.item_id)
        return tuple(seen)

    def citation_line(self) -> str:
        """One line naming what was read, for the UI and for debugging."""
        if not self.hits:
            return "No supporting documents retrieved."
        names = []
        for hit in self.hits:
            label = hit.chunk.section_title or hit.chunk.source
            names.append(f"{label}*" if hit.forced else label)
        return f"Read from {', '.join(names)} ({self.mode})."


class Retriever(Protocol):
    """The seam between retrieval and everything upstream.

    Exists so the in-memory implementation can be swapped for a vector database
    if the corpus ever outgrows a single process, without any caller changing.
    """

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 5,
        query_vector: Sequence[float] | None = None,
        doc_types: Collection[DocType] | None = None,
        force_item_ids: Collection[str] = (),
    ) -> RetrievalResult: ...


def _bigrams(tokens: Sequence[str]) -> tuple[str, ...]:
    return tuple(f"{first} {second}" for first, second in pairwise(tokens))


def _keyword_confidence(score: float) -> float:
    """Squash an unbounded keyword score onto 0-1, monotonically.

    Saturating rather than linear because the difference between a score of 6
    and a score of 12 is not worth twice as much: both mean the request named
    the item plainly. What the scale has to preserve is the ordering and the
    position of the one threshold that matters.
    """
    return score / (score + KEYWORD_HALF_CONFIDENCE) if score > 0 else 0.0


def _dense_confidence(cosine: float) -> float:
    """Rescale a cosine onto 0-1 using the range this corpus actually produces.

    See :data:`DENSE_FLOOR` for the measurements. Clamped at both ends: beyond
    them the extra similarity carries no more information about whether this is
    the right service.
    """
    return min(1.0, max(0.0, (cosine - DENSE_FLOOR) / (DENSE_CEILING - DENSE_FLOOR)))


@dataclass(frozen=True, slots=True)
class _ChunkTerms:
    """Precomputed lookup structures for one chunk, built once at load."""

    hint_tokens: frozenset[str]
    section_tokens: frozenset[str]
    body_tokens: frozenset[str]
    hint_text: str
    body_text: str
    phrases: tuple[frozenset[str], ...]
    """The item name and each alias as its own token set, for coverage scoring."""


class InMemoryRetriever:
    """Hybrid keyword and vector search over an index held in process memory."""

    def __init__(self, index: KnowledgeIndex) -> None:
        self._index = index
        self._chunks = index.retrievable()
        self._terms = tuple(self._build_terms(chunk) for chunk in self._chunks)
        self._idf = self._build_idf()

    @property
    def index(self) -> KnowledgeIndex:
        return self._index

    def __len__(self) -> int:
        return len(self._chunks)

    @staticmethod
    def _build_terms(chunk: Chunk) -> _ChunkTerms:
        hint_source = " ".join((chunk.section_title or "", *chunk.use_when))
        phrases = tuple(
            frozenset(tokens)
            for phrase in (chunk.section_title or "", *chunk.use_when)
            if (tokens := content_tokens(phrase))
        )
        return _ChunkTerms(
            hint_tokens=frozenset(content_tokens(hint_source)),
            section_tokens=frozenset(content_tokens(chunk.section or "")),
            body_tokens=frozenset(content_tokens(chunk.content)),
            # Bigrams are matched against text rather than tokens, so these are
            # stemmed word-by-word to stay comparable with a stemmed query.
            hint_text=" ".join(content_tokens(hint_source)),
            body_text=" ".join(content_tokens(chunk.content)),
            phrases=phrases,
        )

    def _build_idf(self) -> dict[str, float]:
        """Rarer terms count for more. Over 81 near-identically structured
        documents this is what stops boilerplate like 'marketing' or 'team'
        from dominating every score."""
        total = len(self._chunks)
        if not total:
            return {}

        document_frequency: dict[str, int] = {}
        for terms in self._terms:
            for token in terms.body_tokens | terms.hint_tokens | terms.section_tokens:
                document_frequency[token] = document_frequency.get(token, 0) + 1

        return {
            token: math.log(1.0 + total / (1.0 + count))
            for token, count in document_frequency.items()
        }

    def _keyword_score(
        self, tokens: Sequence[str], terms: _ChunkTerms
    ) -> tuple[float, list[str], float]:
        score = 0.0
        matched: list[str] = []

        for token in dict.fromkeys(tokens):
            weight = self._idf.get(token, 0.0)
            if not weight:
                continue
            if token in terms.hint_tokens:
                score += HINT_WEIGHT * weight
                matched.append(token)
            elif token in terms.section_tokens:
                score += SECTION_WEIGHT * weight
                matched.append(token)
            elif token in terms.body_tokens:
                score += BODY_WEIGHT * weight
                matched.append(token)

        for bigram in _bigrams(tokens):
            rarity = sum(self._idf.get(part, 0.0) for part in bigram.split()) / 2.0
            if not rarity:
                continue
            if bigram in terms.hint_text:
                score += BIGRAM_HINT_WEIGHT * rarity
                matched.append(bigram)
            elif bigram in terms.body_text:
                score += BIGRAM_BODY_WEIGHT * rarity
                matched.append(bigram)

        coverage = self._name_coverage(tokens, terms)
        score += NAME_COVERAGE_WEIGHT * coverage

        # Divided by query length so a long question does not simply outscore a
        # short one, and MIN_SCORE means the same thing for both.
        return score / max(len(tokens), 1), matched, coverage

    def _name_coverage(self, tokens: Sequence[str], terms: _ChunkTerms) -> float:
        """How much of this item's identity the query accounts for.

        Weighted by rarity rather than counting words, because words are not
        interchangeable evidence. Covering "regular" in the alias "regular
        meetings" is half the words but almost none of the meaning, while
        covering "translate" in "translation and localisation" is most of it.
        """
        query = set(tokens)
        best = 0.0
        for phrase in terms.phrases:
            total = sum(self._idf.get(token, 0.0) for token in phrase)
            if not total:
                continue
            covered = sum(self._idf.get(token, 0.0) for token in phrase & query)
            best = max(best, covered / total)
        return best

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 5,
        query_vector: Sequence[float] | None = None,
        doc_types: Collection[DocType] | None = None,
        force_item_ids: Collection[str] = (),
    ) -> RetrievalResult:
        if not self._chunks:
            return RetrievalResult(mode="empty", notes=("index is empty",))

        forced_ids = set(force_item_ids)
        eligible = [
            (chunk, terms)
            for chunk, terms in zip(self._chunks, self._terms, strict=True)
            if doc_types is None or chunk.doc_type in doc_types
        ]
        if not eligible:
            return RetrievalResult(mode="empty", notes=("no chunks of the requested type",))

        tokens = content_tokens(query)
        use_dense = query_vector is not None and self._index.has_embeddings
        mode = "keyword+dense" if use_dense else "keyword"

        forced: list[ScoredChunk] = []
        scored: list[ScoredChunk] = []

        for chunk, terms in eligible:
            if tokens:
                keyword, matched, coverage = self._keyword_score(tokens, terms)
            else:
                keyword, matched, coverage = 0.0, [], 0.0

            # Ranking and confidence are blended separately, on purpose. The
            # score keeps its existing shape so relative order is unchanged;
            # the confidence blends two numbers that already mean the same
            # thing, so it stays comparable whichever mode produced it.
            if use_dense and chunk.embedding is not None and query_vector is not None:
                dense = self._cosine(query_vector, chunk.embedding)
                score = DENSE_WEIGHT * dense + KEYWORD_WEIGHT * keyword
                confidence = DENSE_CONFIDENCE_WEIGHT * _dense_confidence(dense) + (
                    KEYWORD_CONFIDENCE_WEIGHT * _keyword_confidence(keyword)
                )
            else:
                score = keyword
                confidence = _keyword_confidence(keyword)

            if chunk.item_id and chunk.item_id in forced_ids:
                forced.append(
                    ScoredChunk(chunk, score, tuple(matched), coverage, confidence, forced=True)
                )
            elif score >= MIN_SCORE:
                scored.append(ScoredChunk(chunk, score, tuple(matched), coverage, confidence))

        # Ordered by confidence, not by score. In keyword-only mode the two
        # are the same ordering, because confidence is then a monotonic
        # function of the score. With embeddings blended in they diverge, and
        # confidence is the one that gets it right: for "who looks after our
        # instagram posts" the top-scoring item was Campaign wrap-ups, an
        # analytics report, at 0.23 confidence.
        scored.sort(key=lambda hit: hit.confidence, reverse=True)
        forced.sort(key=lambda hit: hit.confidence, reverse=True)

        # Forced slices are never evicted by scoring; they take their places
        # first and the remainder of the budget is filled by rank.
        hits = (*forced, *scored[: max(limit - len(forced), 0)])

        notes: list[str] = []
        missing = forced_ids - {hit.chunk.item_id for hit in forced}
        if missing:
            notes.append(f"requested item(s) absent from the index: {', '.join(sorted(missing))}")
        if not tokens:
            notes.append("query produced no searchable tokens")

        if not hits:
            return RetrievalResult(mode=mode, notes=(*notes, "nothing scored above the threshold"))

        if forced and not scored:
            mode = "forced-only"

        return RetrievalResult(hits=hits, mode=mode, notes=tuple(notes))


def build_retriever(index: KnowledgeIndex) -> InMemoryRetriever:
    """Factory kept separate so callers depend on the protocol, not the class."""
    return InMemoryRetriever(index)


def describe(chunks: Iterable[Chunk]) -> str:
    """Format chunks for a prompt, one labelled block each."""
    return "\n\n---\n\n".join(chunk.content for chunk in chunks)
