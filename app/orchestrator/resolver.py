"""Deciding which service a request is about, and therefore what it costs.

This module answers the only question that really matters - is this in scope? -
and it does so with a dictionary lookup. No model output reaches it. That is
what makes a prompt injection unable to change a verdict, and what makes "I
could not tell which service you mean" a real answer rather than a confident
wrong one.

Four outcomes, and the middle two are the interesting ones:

``RESOLVED``
    One service. Straightforward.

``AGREED``
    Several plausible services that all carry the *same* verdict. The item is
    still unidentified, but the question the user actually asked is already
    answered, so asking them to choose would be busywork. "Whether you mean
    Billboards or Hoarding, both need a quote" is a better reply than a menu.

``AMBIGUOUS``
    Several plausible services whose verdicts *disagree*. Here the choice
    changes the answer, so it has to be put to the user. This is the case a
    similarity score must never decide: in this corpus, "ad editing" points at
    one item that is in scope and another that needs a quote.

``UNKNOWN``
    Nothing matched well enough. Routes to a human, and is a success, not a
    failure.

Matching runs in descending order of confidence. Phrase containment first,
which is exact and needs no scoring; keyword retrieval only as a fallback, and
only when it wins by a clear margin.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

import structlog

from app.core.keys import content_tokens
from app.core.types import ServiceItem, Status
from app.knowledge.catalog import ServiceCatalog
from app.knowledge.retriever import Retriever, ScoredChunk

__all__ = ["Candidate", "Outcome", "Resolution", "ScopeResolver"]

logger = structlog.get_logger(__name__)

MAX_CANDIDATES = 4
"""More options than this is not a question, it is a wall. Past four the honest
answer is that the request was too vague, which routes to a human."""

MIN_CONFIDENT_SCORE = 1.6
"""Keyword score below which a match is not worth acting on. Tuned against
evals/retrieval.json, where genuine matches score above 3 and noise below 1.5.
Prefer UNKNOWN over a weak guess: a wrong verdict costs more than a handover."""

RIVAL_FLOOR = 0.5
"""How close a runner-up must be, as a fraction of the leader's score, before
it can be considered at all."""

MIN_SINGLE_TERM_COVERAGE = 0.5
"""How much of an item's name a *lone* matched term must account for.

Applies only when the request matched exactly one term. "Merch" is one word and
the item's entire identity, so it resolves; "one" is one word from somebody's
body text, so it does not. See :func:`_is_evidence`."""

MIN_RIVAL_COVERAGE = 0.25
"""How much of its own name a runner-up must account for to count as a real
alternative rather than a lower score.

A score gap cannot tell a winner from a tie: one case here needed the leader
27% ahead to be trusted while another was still a coin toss at 34%, so no
single margin separates them. Name coverage does separate them, because it
asks a different question - did the request actually name this thing?

"Translate our web pages" puts the copywriting item 45% clear on score, but
"translate" is half the identity of Translation & localisation, so it is a
genuine alternative and the two disagree about scope. "Photography for a
magazine advert" puts two items within 3%, yet the runner-up is Local
opportunities (radio, magazines, podcasts) and one word out of six is not that
service being requested."""

MAX_DOCUMENTS_FOR_A_DECISIVE_WORD = 4
"""A phrase may only settle a request outright if at least one of its words
appears in no more than this many documents.

Rarity, not length, is what makes a name worth trusting. The Copywriting
section names its items after the thing being written, so the corpus contains
items called simply Emails, Web pages and Paid ads. Every word in those names
is everywhere in the corpus, and matching them literally sent "set up emails
for people who abandon their booking" to the copywriting item, which is not
what anyone meant. Requiring two words did not help, because "web pages" is two
common words. Phrases anchored by something distinctive - Billboards, Merch,
POS - still settle a request on the spot; the rest defer to scoring."""


class Outcome(StrEnum):
    RESOLVED = "resolved"
    AGREED = "agreed"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Candidate:
    item: ServiceItem
    score: float
    reason: str
    """Why this item is here, in words, for logs and for the UI."""


@dataclass(frozen=True, slots=True)
class Resolution:
    """What the resolver concluded, and how."""

    outcome: Outcome
    query: str
    candidates: tuple[Candidate, ...] = ()
    matched_phrase: str | None = None
    method: str = "none"
    """``phrase`` or ``keyword``. Surfaced so any verdict can be traced back to
    the reason it was reached."""

    @property
    def item(self) -> ServiceItem | None:
        """The single service, when there is one."""
        return self.candidates[0].item if self.outcome is Outcome.RESOLVED else None

    @property
    def items(self) -> tuple[ServiceItem, ...]:
        return tuple(candidate.item for candidate in self.candidates)

    @property
    def decided(self) -> bool:
        """Whether a verdict can be stated. True for RESOLVED and AGREED."""
        return self.outcome in (Outcome.RESOLVED, Outcome.AGREED)

    @property
    def status(self) -> Status | None:
        """The verdict, or ``None`` when the resolver could not reach one."""
        return self.candidates[0].item.status if self.decided else None

    @property
    def status_meaning(self) -> str | None:
        """The corpus's own wording for the verdict.

        Preferred over anything phrased in code so that the documents stay the
        single source of truth for how a verdict is described.
        """
        return self.candidates[0].item.status_meaning if self.decided else None

    @property
    def force_item_ids(self) -> tuple[str, ...]:
        """Items retrieval must include regardless of score.

        A job cannot be done without the slice it is about, so once the
        resolver has named a service its chunk goes into the pack directly
        rather than being left to compete for a place.
        """
        return tuple(candidate.item.item_id for candidate in self.candidates)

    def question(self) -> str | None:
        """The clarifying question to ask, when one is genuinely needed."""
        if self.outcome is not Outcome.AMBIGUOUS:
            return None
        options = "\n".join(
            f"{number}. {candidate.item.display_name}"
            for number, candidate in enumerate(self.candidates, start=1)
        )
        return (
            "A few different services could match that, and they are not "
            f"handled the same way. Which do you mean?\n{options}"
        )

    def explain(self) -> str:
        """One line describing how this conclusion was reached."""
        if self.outcome is Outcome.UNKNOWN:
            return f"No service matched {self.query!r}."
        via = f"{self.method} match"
        if self.matched_phrase:
            via += f" on {self.matched_phrase!r}"
        names = ", ".join(
            f"{candidate.item.display_name} [{candidate.score:.2f}]"
            for candidate in self.candidates
        )
        return f"{self.outcome.value} via {via}: {names}"


@dataclass(frozen=True, slots=True)
class _Phrase:
    """One searchable name or alias, pre-tokenised for containment testing."""

    tokens: tuple[str, ...]
    item_id: str
    original: str


class ScopeResolver:
    """Maps a request onto a catalog item and its verdict."""

    def __init__(self, catalog: ServiceCatalog, retriever: Retriever | None = None) -> None:
        self._catalog = catalog
        self._retriever = retriever
        self._phrases = self._build_phrases(catalog)
        self._document_frequency = self._build_document_frequency(catalog)

    @staticmethod
    def _build_phrases(catalog: ServiceCatalog) -> tuple[_Phrase, ...]:
        phrases = [
            _Phrase(tokens=tokens, item_id=item.item_id, original=term)
            for item in catalog
            for term in item.search_terms
            if (tokens := content_tokens(term))
        ]
        # Longest first, so the most specific phrase that fits is found before
        # any shorter phrase contained within it.
        phrases.sort(key=lambda phrase: len(phrase.tokens), reverse=True)
        return tuple(phrases)

    @staticmethod
    def _build_document_frequency(catalog: ServiceCatalog) -> Counter[str]:
        """How many documents each word appears in, for judging distinctiveness."""
        frequency: Counter[str] = Counter()
        for item in catalog:
            frequency.update(
                set(content_tokens(item.body)) | set(content_tokens(" ".join(item.search_terms)))
            )
        return frequency

    def _is_decisive(self, tokens: tuple[str, ...]) -> bool:
        """Whether matching this phrase is enough to settle the request alone."""
        rarest = min(self._document_frequency[token] for token in tokens)
        return rarest <= MAX_DOCUMENTS_FOR_A_DECISIVE_WORD

    def resolve(self, query: str) -> Resolution:
        tokens = content_tokens(query)
        if not tokens:
            return Resolution(Outcome.UNKNOWN, query)

        resolution = self._resolve_by_phrase(query, tokens)
        if resolution is not None:
            return resolution
        return self._resolve_by_keyword(query)

    def _resolve_by_phrase(self, query: str, tokens: tuple[str, ...]) -> Resolution | None:
        """Find the longest declared name or alias contained in the request.

        Exact and deterministic: either the words are there in order or they
        are not. This handles the majority of requests with no scoring and no
        embedding call.
        """
        best_length = 0
        matches: list[_Phrase] = []

        for phrase in self._phrases:
            if len(phrase.tokens) < best_length:
                break  # sorted longest-first, so nothing better remains
            if _contains(tokens, phrase.tokens):
                best_length = len(phrase.tokens)
                matches.append(phrase)

        if not matches or not self._is_decisive(matches[0].tokens):
            return None

        seen: dict[str, str] = {}
        for phrase in matches:
            seen.setdefault(phrase.item_id, phrase.original)

        candidates = tuple(
            Candidate(
                item=self._catalog.require(item_id),
                score=float(best_length),
                reason=f"declares {original!r}",
            )
            for item_id, original in seen.items()
        )
        phrase_text = matches[0].original
        return self._conclude(query, candidates, method="phrase", matched_phrase=phrase_text)

    def _resolve_by_keyword(self, query: str) -> Resolution:
        """Fall back to scoring when nothing distinctive was named outright.

        A runner-up counts as a real rival only when it scores comparably
        *and* the request named a substantial part of what it is. See
        :data:`MIN_RIVAL_COVERAGE` for why the second condition carries the
        weight rather than the score gap.
        """
        if self._retriever is None:
            return Resolution(Outcome.UNKNOWN, query, method="phrase")

        hits = [
            hit
            for hit in self._retriever.retrieve(query, limit=MAX_CANDIDATES + 1).hits
            if hit.chunk.item_id and hit.score >= MIN_CONFIDENT_SCORE and _is_evidence(hit)
        ]
        if not hits:
            return Resolution(Outcome.UNKNOWN, query, method="keyword")

        leader, *rest = hits
        floor = leader.score * RIVAL_FLOOR

        contenders = [leader]
        for hit in rest:
            if hit.score < floor:
                break
            if hit.coverage >= MIN_RIVAL_COVERAGE:
                contenders.append(hit)

        candidates = tuple(
            Candidate(
                item=self._catalog.require(str(hit.chunk.item_id)),
                score=hit.score,
                reason=f"matched {', '.join(hit.matched)}" if hit.matched else "keyword match",
            )
            for hit in contenders
        )
        return self._conclude(query, candidates, method="keyword", matched_phrase=None)

    @staticmethod
    def _conclude(
        query: str,
        candidates: tuple[Candidate, ...],
        *,
        method: str,
        matched_phrase: str | None,
    ) -> Resolution:
        """Turn a set of candidates into an outcome.

        The whole decision rests on one question: do these candidates agree
        about the verdict? If they do, the user's question is answered and
        which item they meant is a detail. If they do not, the choice changes
        the answer and only the user can make it.
        """
        if not candidates:
            return Resolution(Outcome.UNKNOWN, query, method=method)

        if len(candidates) == 1:
            return Resolution(
                Outcome.RESOLVED,
                query,
                candidates=candidates,
                matched_phrase=matched_phrase,
                method=method,
            )

        # Agreement is checked before the candidate count, and the order
        # matters. A broad request that lands on six items which all say the
        # same thing is answerable, and discarding it for being broad threw
        # away six services that could then never be asked about at all.
        verdicts = {candidate.item.status for candidate in candidates}
        if len(verdicts) == 1:
            return Resolution(
                Outcome.AGREED,
                query,
                candidates=candidates,
                matched_phrase=matched_phrase,
                method=method,
            )

        if len(candidates) > MAX_CANDIDATES:
            logger.info("resolver.too_vague", query=query, candidates=len(candidates))
            return Resolution(Outcome.UNKNOWN, query, method=method)

        return Resolution(
            Outcome.AMBIGUOUS,
            query,
            candidates=candidates,
            matched_phrase=matched_phrase,
            method=method,
        )


def _is_evidence(hit: ScoredChunk) -> bool:
    """Whether a hit identifies a service, or merely shares a word with one.

    A score alone cannot tell these apart, because scores are normalised by
    query length: a one-word message puts its entire weight on a single term,
    so any rare word it happens to contain scores as highly as a fully
    specified request. The bare word "one" scored 12 against an item whose
    body mentions it once, comfortably clearing every threshold.

    Raising the threshold would not fix that - it would only reject genuine
    short requests like "merch" alongside it. The distinction is not how much
    the query scored but *what it named*: one term is enough when that term is
    most of the item's identity, and never enough when it is a word from the
    body.
    """
    return len(hit.matched) > 1 or hit.coverage >= MIN_SINGLE_TERM_COVERAGE


def _contains(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    """Whether ``needle`` appears as a contiguous run inside ``haystack``."""
    if not needle or len(needle) > len(haystack):
        return False
    first = needle[0]
    span = len(needle)
    for start in range(len(haystack) - span + 1):
        if haystack[start] == first and haystack[start : start + span] == needle:
            return True
    return False
