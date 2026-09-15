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
from app.knowledge.embeddings import Embedder
from app.knowledge.retriever import Retriever, ScoredChunk

__all__ = ["Candidate", "Outcome", "Resolution", "ScopeResolver"]

logger = structlog.get_logger(__name__)

MAX_CANDIDATES = 4
"""More options than this is not a question, it is a wall. Past four the honest
answer is that the request was too vague, which routes to a human."""

MIN_CONFIDENCE = 0.5
"""Confidence below which a match is not worth acting on. Prefer UNKNOWN over
a weak guess: a wrong verdict costs more than a handover.

Expressed as confidence rather than as a raw score because this is an
*absolute* judgement — is this good enough to act on at all — and a raw score
does not mean the same thing from one retrieval mode to the next. Blended
scoring is ``0.75 x cosine + 0.25 x keyword``; cosine cannot exceed 1, so the
old floor of 1.6 would have required the keyword half alone to reach 3.4 the
moment embeddings were switched on, and almost every correct answer would have
fallen below it. A threshold that changes meaning when a flag changes is not a
threshold.

0.5 against :data:`~app.knowledge.retriever.KEYWORD_HALF_CONFIDENCE` accepts
exactly the hits the old floor of 1.6 accepted in keyword-only mode."""

RIVAL_FLOOR = 0.85
"""How close a runner-up must be, as a fraction of the leader's confidence,
before it counts as a genuine alternative rather than the next thing down.

Compares confidence, like everything else that ranks or admits, because two
orderings inside one decision is how the leader of a query ends up being an
item nothing else agreed was relevant.

Higher than it looks, for two reasons. Confidence saturates where score does
not, so the same pair of hits sits closer together on this scale than on the
old one — 0.85 here admits roughly what 0.5 admitted before. And a rival's job
is to represent a real second reading of the request, not to be the runner-up:
"Can central team schedule our Instagram posts?" put Content scheduling at
0.74 and an SEO content-calendar item at 0.51, and pairing those two turned a
plain question into a menu.

Swept against the whole turn suite with embeddings on: 0.50 and 0.60 score
66/74, 0.70 to 0.80 score 69/74, and 0.85 upwards score 70/74. Raising it does
not suppress genuine disagreement — a request that truly names two services
gets its second candidate from :meth:`ScopeResolver._check_for_disagreement`,
which does not consult this at all."""

MIN_SINGLE_TERM_COVERAGE = 0.5
"""How much of an item's name a *lone* matched term must account for.

Applies only when the request matched exactly one term, and is necessary
rather than sufficient: the term must also be rare. "Merch" is one word, the
item's entire identity, and used in one document; "one" is a word from
somebody's body text; "website" is most of an alias but appears in thirteen
documents, which is why it must not carry a verdict on its own. See
:meth:`ScopeResolver._is_evidence`."""

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

WEAK_FREE_VERDICT = 0.73
"""Confidence below which an in-scope answer is not trusted on its own.

A free verdict is the expensive one to get wrong. Telling somebody a chargeable
service is covered costs real money when the invoice arrives; asking which of
two services they meant costs a click. So a weak "in scope" has to survive a
second look at what else the request could have been, and a strong one does not.

The failure this exists for: "I need to send an email about an upcoming event"
answered Emails (Copywriting), in scope, at 0.51-0.69 — the top of a flat
cluster of eleven email services, barely clear of :data:`MIN_CONFIDENCE`. Ad hoc
email requests, which needs a quote and lists event invitations as an example,
sat just below the floor and was never looked at.

Swept with embeddings on against every retrieval and turn prompt, and against the
phrases the model planner actually produced for those turns — which score
differently from the raw messages, and are what production resolves. The
requests that should have been questioned led at 0.52-0.69; every in-scope answer
that must stay an answer, and that has a costlier service anywhere near it, led
at 0.77 or above. Set between the two."""

COSTLIER_LOOKALIKE = 0.73
"""How close a chargeable or venue-handled service must read, as a fraction of a
weak in-scope leader's confidence, to put the verdict to the user.

Deliberately does not ask whether the request *named* the service, which is the
test :data:`MIN_RIVAL_COVERAGE` applies. That test is exactly what missed the
email case: the request said "email", Ad hoc email requests is named mostly by
other words, and it was rejected at 0.2 coverage. A lookalike is a service that
means nearly the same thing, not one that shares the words.

Measured alongside :data:`WEAK_FREE_VERDICT`, among weak leaders only. Requests
that should have been questioned had their costlier lookalike at 0.76-0.86 of the
leader; in-scope answers that must stand had theirs at 0.69 or below — Campaign
wrap-ups against Radio ads is the nearest, at 0.69. Set between the two."""

LOOKALIKE_DEPTH = 8
"""How far down the ranking to look for a costlier lookalike.

Deeper than the candidates the resolver keeps, because the point is to find what
the ordinary admission rules discarded: in the email case the quoted service was
fifth of six. Costs nothing extra — retrieval scores every chunk and truncates,
so this is the same search with a longer tail kept."""


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
            "A couple of services could match that, and they aren't handled the "
            f"same way — which one did you mean?\n{options}"
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


STEM_LENGTH = 6
"""How many leading characters of a word are treated as its identity.

Exact tokens miss the way people conjugate: "translating our web pages" shares no
token with an item called Translation & localisation, so a request that named two
services that disagree looked like a request that named one. Six characters is
enough to keep translate/translating/translation together while keeping
photo/photography apart from photoshoot, which are different items."""


@dataclass(frozen=True, slots=True)
class _Phrase:
    """One searchable name or alias, pre-tokenised for containment testing."""

    tokens: tuple[str, ...]
    item_id: str
    original: str


@dataclass(frozen=True, slots=True)
class _Identity:
    """One name or alias, reduced to stems, for spotting a service by hand."""

    item_id: str
    stems: frozenset[str]
    distinctive: frozenset[str]
    """The stems of this name's rare words. Without one of these, a stem overlap
    is a shared English word rather than a service being named."""

    name_stems: frozenset[str]
    """Stems of the item's short name. A rival has to be named as a service,
    not as a place that happens to appear in its title ("merch for London"
    is merch, not the London video-visit item)."""

    original: str


def _stems(tokens: tuple[str, ...]) -> frozenset[str]:
    return frozenset(token[:STEM_LENGTH] for token in tokens)


class ScopeResolver:
    """Maps a request onto a catalog item and its verdict."""

    def __init__(
        self,
        catalog: ServiceCatalog,
        retriever: Retriever | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._catalog = catalog
        self._retriever = retriever
        self._embedder = embedder
        self._phrases = self._build_phrases(catalog)
        self._document_frequency = self._build_document_frequency(catalog)
        self._identities = self._build_identities(catalog)

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

    def _build_identities(self, catalog: ServiceCatalog) -> tuple[_Identity, ...]:
        identities = []
        for item in catalog:
            name_stems = _stems(content_tokens(item.item))
            for term in item.search_terms:
                tokens = content_tokens(term)
                if not tokens:
                    continue
                distinctive = tuple(
                    token
                    for token in tokens
                    if self._document_frequency[token] <= MAX_DOCUMENTS_FOR_A_DECISIVE_WORD
                )
                identities.append(
                    _Identity(
                        item_id=item.item_id,
                        stems=_stems(tokens),
                        distinctive=_stems(distinctive),
                        name_stems=name_stems,
                        original=term,
                    )
                )
        return tuple(identities)

    def _is_decisive(self, tokens: tuple[str, ...]) -> bool:
        """Whether matching this phrase is enough to settle the request alone."""
        rarest = min(self._document_frequency[token] for token in tokens)
        return rarest <= MAX_DOCUMENTS_FOR_A_DECISIVE_WORD

    def _query_vector(self, query: str) -> tuple[float, ...] | None:
        """Embed the phrase being resolved, or ``None`` to score on words alone.

        Failure is not an error here. An unreachable embedding backend returns
        ``None`` and retrieval degrades to keyword within the same turn, which
        is the behaviour the whole hybrid design is built around: dense search
        improves the ranking, and nothing depends on it existing.
        """
        if self._embedder is None:
            return None
        return self._embedder.embed_query(query)

    def _frequency_of(self, hit: ScoredChunk) -> int:
        """How many documents this hit's lone matched term appears in.

        A bigram carries no frequency of its own, so it is judged by its
        commonest half — the weakest claim it can make. Only meaningful when
        exactly one term matched, which is the only case that consults it.
        """
        if not hit.matched:
            return 0
        return max(
            (self._document_frequency[part] for part in hit.matched[0].split()),
            default=0,
        )

    def resolve(self, query: str) -> Resolution:
        tokens = content_tokens(query)
        if not tokens:
            return Resolution(Outcome.UNKNOWN, query)

        # Retrieval runs only when the phrase path did not settle it, so the
        # fast path still pays nothing. Its hits are then shared with the
        # disagreement check, which needs to know what retrieval made of a
        # rival before promoting it.
        resolution = self._resolve_by_phrase(query, tokens)
        hits: tuple[ScoredChunk, ...] = ()
        ranked: tuple[ScoredChunk, ...] = ()
        semantic = False
        if resolution is None:
            hits, semantic, ranked = self._retrieve(query)
            resolution = self._resolve_by_keyword(query, hits)
        resolution = self._check_for_disagreement(resolution, tokens, hits, semantic)
        return self._check_for_costlier_lookalike(resolution, ranked, semantic)

    def _retrieve(
        self, query: str
    ) -> tuple[tuple[ScoredChunk, ...], bool, tuple[ScoredChunk, ...]]:
        """Hits worth considering at all, best first, and whether they are
        semantic.

        Embedded here rather than upstream: the phrase this resolves is not
        always the question the rest of the turn retrieves on, so a vector
        computed elsewhere would be a vector for different words.

        The flag travels with the hits because one downstream judgement is only
        sound when embeddings contributed — see
        :meth:`_check_for_disagreement`.
        """
        if self._retriever is None:
            return (), False, ()
        vector = self._query_vector(query)
        result = self._retriever.retrieve(
            query, limit=max(MAX_CANDIDATES + 1, LOOKALIKE_DEPTH), query_vector=vector
        )
        # The admission rules see exactly the slice they always saw. Retrieval
        # sorts every chunk and truncates, so the first MAX_CANDIDATES + 1 of a
        # longer list are the same hits a shorter request returns; only the
        # lookalike check reads past them.
        hits = tuple(
            hit
            for hit in result.hits[: MAX_CANDIDATES + 1]
            if hit.chunk.item_id
            and hit.confidence >= MIN_CONFIDENCE
            and _is_evidence(hit, self._frequency_of(hit))
        )
        return hits, "dense" in result.mode, tuple(result.hits)

    def _check_for_disagreement(
        self,
        resolution: Resolution,
        tokens: tuple[str, ...],
        hits: tuple[ScoredChunk, ...],
        semantic: bool,
    ) -> Resolution:
        """Withdraw a verdict when the request also named a service that disagrees.

        Both paths above pick a winner and stop looking. That is right when the
        alternatives say the same thing, and dangerous when they do not: "do you
        handle translating our web pages" resolves outright to Web pages, which
        is free of charge, while Translation & localisation — named just as
        plainly — belongs to the local site. Answering the first one is not a
        near miss, it is telling someone their job is covered when it is not.

        So a decided verdict is re-checked against every service the request
        named by word, and any disagreement turns the answer into a question.
        Agreement is left alone, because then the choice does not matter.

        Naming a service is necessary here but not sufficient, because words
        appear in sentences for reasons of their own. "Can we get a wrap-up on
        how the Heart Radio campaign performed?" contains the word radio, and
        that used to be enough to raise Radio ads — a chargeable design item —
        against a plainly correct answer, and turn a control question into a
        menu. Heart Radio is a station.

        What separates that from the translation case is not the word but how
        convincing retrieval found the rival. With embeddings in the blend a
        genuine second reading sits at 0.88 to 1.00 of the leader's confidence
        and the radio coincidence at 0.69, so a rival must also clear
        :data:`RIVAL_FLOOR` — the same bar a runner-up clears to be admitted
        normally, one notion of "close enough to be a real alternative" used in
        both places.

        **Only when the hits are semantic.** On keyword scoring alone the two
        populations overlap and no threshold separates them: the same four
        requests measure 0.77 to 0.99 for genuine disagreement against 0.79 for
        the radio coincidence. Telling a second reading from a shared word is a
        question about meaning, and word counts cannot answer it. So without
        embeddings the check falls back to naming alone, which asks more often
        than it needs to — the safe direction, and the reason this degrades
        rather than guesses.
        """
        if not resolution.decided:
            return resolution

        verdict = resolution.status
        chosen = {candidate.item.item_id for candidate in resolution.candidates}
        query_stems = _stems(tokens)
        confidence = {hit.chunk.item_id: hit.confidence for hit in hits}
        # Applied only when retrieval was semantic and actually ran; otherwise
        # naming is all there is to go on, as it was before.
        gated = semantic and bool(hits)
        floor = max(confidence.values(), default=0.0) * RIVAL_FLOOR

        rivals: dict[str, Candidate] = {}
        for identity in self._identities:
            if identity.item_id in chosen or identity.item_id in rivals:
                continue
            if not identity.distinctive & query_stems:
                continue
            # Named as a service, not as a place-word in somebody else's title.
            if not identity.name_stems:
                continue
            named = identity.name_stems & query_stems
            if len(named) / len(identity.name_stems) < MIN_RIVAL_COVERAGE:
                continue
            if gated and confidence.get(identity.item_id, 0.0) < floor:
                continue
            item = self._catalog.require(identity.item_id)
            if item.status is verdict:
                continue
            rivals[item.item_id] = Candidate(
                item=item,
                score=float(len(named)),
                reason=f"also named {identity.original!r}",
            )

        if not rivals:
            return resolution

        candidates = resolution.candidates + tuple(rivals.values())
        logger.info(
            "resolver.disagreement",
            query=resolution.query,
            chose=resolution.candidates[0].item.display_name,
            rivals=[candidate.item.display_name for candidate in rivals.values()],
        )
        return Resolution(
            Outcome.AMBIGUOUS,
            resolution.query,
            candidates=candidates[:MAX_CANDIDATES],
            matched_phrase=resolution.matched_phrase,
            method=f"{resolution.method}+rival",
        )

    def _check_for_costlier_lookalike(
        self,
        resolution: Resolution,
        ranked: tuple[ScoredChunk, ...],
        semantic: bool,
    ) -> Resolution:
        """Put a weak "in scope" to the user when a costlier service reads alike.

        The disagreement check above catches a request that *names* two services.
        This catches one that names neither clearly, lands on a free item by a
        hair, and has a chargeable or venue-handled service reading almost the
        same — which no amount of naming will surface, because the words that
        identify that service were never typed.

        One-directional on purpose. It questions an in-scope answer and never a
        costly one: see :data:`WEAK_FREE_VERDICT` for why those two mistakes are
        not the same size. And it leaves a phrase match alone, since a request
        that spelled out a service's declared name has already said which it
        meant.

        **Only when retrieval was semantic**, for the reason the disagreement
        check gives. On keyword scores the two populations overlap: a request
        for the marketing calendar would be questioned while one of the email
        cases this exists for would still be answered. Without embeddings the
        resolver keeps its old behaviour rather than trading one wrong answer
        for another.
        """
        if not semantic or not ranked:
            return resolution
        if not resolution.decided or resolution.status is not Status.IN_SCOPE:
            return resolution
        if resolution.method != "keyword":
            return resolution

        chosen = {candidate.item.item_id for candidate in resolution.candidates}
        leading = [hit for hit in ranked if hit.chunk.item_id in chosen]
        lead = max((hit.confidence for hit in leading), default=0.0)
        if lead <= 0.0 or lead >= WEAK_FREE_VERDICT:
            return resolution

        # The words that made the leader the leader. A lookalike has to be read
        # from some of the same ones, or it is not a second reading of this
        # request at all — it is a different subject that happens to share a
        # word. "Heart Radio campaign wrap-up" put Radio ads within reach of
        # Campaign wrap-ups on the word "radio" alone, and questioning it would
        # have undone the fix for exactly that coincidence. The email case
        # passes this on "email", which is the thing both services are about.
        evidence = {term for hit in leading for term in hit.matched}

        floor = lead * COSTLIER_LOOKALIKE
        lookalikes: dict[str, Candidate] = {}
        for hit in ranked:
            item_id = hit.chunk.item_id
            if not item_id or item_id in chosen or item_id in lookalikes:
                continue
            if hit.confidence < floor:
                continue
            if not evidence.intersection(hit.matched):
                continue
            item = self._catalog.get(item_id)
            if item is None or item.status is Status.IN_SCOPE:
                continue
            lookalikes[item_id] = Candidate(
                item=item,
                score=hit.score,
                reason="reads nearly the same, and is not free",
            )

        if not lookalikes:
            return resolution

        logger.info(
            "resolver.costlier_lookalike",
            query=resolution.query,
            chose=resolution.candidates[0].item.display_name,
            lead=round(lead, 3),
            lookalikes=[candidate.item.display_name for candidate in lookalikes.values()],
        )
        # The leader, then what it could be mistaken for, then anything it had
        # agreed with. Trimming happens after, and in this order the question
        # can never lose the one option that makes it a question: an AGREED
        # set of four free services plus a lookalike, trimmed from the end,
        # would otherwise drop the lookalike and ask about four things that
        # all say the same.
        leader, *agreed = resolution.candidates
        candidates = (leader, *lookalikes.values(), *agreed)
        return Resolution(
            Outcome.AMBIGUOUS,
            resolution.query,
            candidates=candidates[:MAX_CANDIDATES],
            matched_phrase=resolution.matched_phrase,
            method=f"{resolution.method}+lookalike",
        )

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

        # Several names can be the same length, and which one the scan reached
        # first is an accident of catalog order. Judging only that one meant a
        # request naming both a common word and a distinctive one — "email my
        # AM about the merch request" — was thrown away because "email" is
        # everywhere, even though "merch" settles it outright.
        decisive = [phrase for phrase in matches if self._is_decisive(phrase.tokens)]
        if not decisive:
            return None
        matches = decisive

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

    def _resolve_by_keyword(
        self, query: str, hits: tuple[ScoredChunk, ...]
    ) -> Resolution:
        """Fall back to scoring when nothing distinctive was named outright.

        A runner-up counts as a real rival only when it is nearly as convincing
        as the leader *and* the request named a substantial part of what it is.
        See :data:`MIN_RIVAL_COVERAGE` for why the second condition carries the
        weight rather than the gap alone.
        """
        if self._retriever is None:
            return Resolution(Outcome.UNKNOWN, query, method="phrase")
        if not hits:
            return Resolution(Outcome.UNKNOWN, query, method="keyword")

        leader, *rest = hits
        floor = leader.confidence * RIVAL_FLOOR

        contenders = [leader]
        for hit in rest:
            if hit.confidence < floor:
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

        # A crowded field is trimmed, not thrown away. This used to return
        # UNKNOWN, on the reasoning that more than four options is a wall
        # rather than a question - true of what gets *shown*, but it was
        # discarding the leader along with the noise. "Can you make new
        # graphics for our in-venue screens?" put Graphics for screens first,
        # with a name the request covers entirely, and answered "I couldn't
        # tell which service you mean" because four weaker items came along.
        #
        # Candidates arrive ordered by confidence, so trimming keeps the best
        # of them. Whether the request was too vague to answer is a question
        # about confidence, and that is now measured directly.
        if len(candidates) > MAX_CANDIDATES:
            logger.info("resolver.crowded", query=query, candidates=len(candidates))
            candidates = candidates[:MAX_CANDIDATES]

        return Resolution(
            Outcome.AMBIGUOUS,
            query,
            candidates=candidates,
            matched_phrase=matched_phrase,
            method=method,
        )


def _is_evidence(hit: ScoredChunk, frequency: int) -> bool:
    """Whether a hit identifies a service, or merely shares a word with one.

    A score alone cannot tell these apart, because scores are normalised by
    query length: a one-word message puts its entire weight on a single term,
    so any rare word it happens to contain scores as highly as a fully
    specified request. The bare word "one" scored 12 against an item whose
    body mentions it once, comfortably clearing every threshold.

    Raising the threshold would not fix that - it would only reject genuine
    short requests like "merch" alongside it. The distinction is not how much
    the query scored but *what it named*.

    So a lone term has to pass two tests, and the second is what stops a
    generic noun speaking for a service. It must account for most of the
    item's identity **and** be rare enough that using it was a choice. "Can
    you build us a new website from scratch" matched only "website", which is
    59% of the alias "website content" - enough on coverage alone to answer
    Web pages, in scope, free of charge, for something this corpus does not
    offer at all. Coverage says the word fits the name; rarity says the word
    was aimed at it.

    ``frequency`` is how many documents the term appears in, passed in rather
    than looked up so the policy stays a pure function of its inputs and does
    not change meaning when somebody edits the corpus.
    """
    if len(hit.matched) > 1:
        return True
    if hit.coverage < MIN_SINGLE_TERM_COVERAGE:
        return False
    return 0 < frequency <= MAX_DOCUMENTS_FOR_A_DECISIVE_WORD


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
