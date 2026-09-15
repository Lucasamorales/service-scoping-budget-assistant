"""Invariants of the scope resolver.

The safety property under test throughout: the resolver never states a verdict
it is not entitled to. Asking, or handing over, is always available and always
preferable to a confident wrong answer about what something costs.

Numbers describing today's corpus live in ``evals/retrieval.json`` and are
scored by ``scripts.eval_resolver`` rather than asserted here.
"""

from __future__ import annotations

import pytest

from app.core.types import Chunk, DocType, Status
from app.knowledge.chunking import chunk_service_item
from app.knowledge.index import KnowledgeIndex
from app.knowledge.retriever import InMemoryRetriever, RetrievalResult, ScoredChunk
from app.orchestrator.resolver import (
    MAX_CANDIDATES,
    Outcome,
    ScopeResolver,
    _is_evidence,
)


@pytest.fixture(scope="module")
def resolver(corpus) -> ScopeResolver:
    chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
    return ScopeResolver(corpus.catalog, InMemoryRetriever(KnowledgeIndex.build(chunks)))


@pytest.fixture(scope="module")
def catalog_only(corpus) -> ScopeResolver:
    return ScopeResolver(corpus.catalog)


class TestDegradedInputs:
    def test_an_empty_request_is_unknown(self, resolver: ScopeResolver) -> None:
        assert resolver.resolve("").outcome is Outcome.UNKNOWN

    def test_a_request_of_only_stopwords_is_unknown(self, resolver: ScopeResolver) -> None:
        assert resolver.resolve("can we do it please").outcome is Outcome.UNKNOWN

    def test_nonsense_is_unknown_rather_than_a_guess(self, resolver: ScopeResolver) -> None:
        assert resolver.resolve("xyzzy plugh frobnicate").outcome is Outcome.UNKNOWN

    @pytest.mark.parametrize(
        "filler",
        ["one", "the first one", "the second one", "yes", "no thanks", "ok", "maybe later"],
    )
    def test_conversational_filler_never_earns_a_verdict(
        self, resolver: ScopeResolver, filler: str
    ) -> None:
        """Regression, and the worst class of bug this system can have.

        "one" was rare enough across 81 documents to score 12 on its own and
        won a confident verdict for an unrelated email item, because a one-word
        query concentrates the whole length-normalised score onto one term.
        """
        assert resolver.resolve(filler).status is None

    def test_a_lone_word_that_is_the_whole_name_still_resolves(
        self, resolver: ScopeResolver
    ) -> None:
        """The other side of the guard above. Rejecting every single-term match
        would throw away legitimate one-word requests."""
        assert resolver.resolve("merch").status is Status.QUOTE_REQUIRED

    def test_unknown_carries_no_verdict(self, resolver: ScopeResolver) -> None:
        """The failure this prevents is an Account Manager being told a
        chargeable service is free because nothing matched."""
        resolution = resolver.resolve("xyzzy plugh frobnicate")
        assert resolution.status is None
        assert resolution.status_meaning is None
        assert resolution.item is None
        assert not resolution.decided

    def test_it_works_with_no_retriever_at_all(self, catalog_only: ScopeResolver) -> None:
        """Phrase matching needs only the catalog, so a missing or unreadable
        index degrades the resolver rather than disabling it."""
        assert catalog_only.resolve("merch").outcome is Outcome.RESOLVED

    def test_without_a_retriever_a_paraphrase_is_unknown_not_wrong(
        self, catalog_only: ScopeResolver
    ) -> None:
        assert catalog_only.resolve("something to hand out at reception").outcome is (
            Outcome.UNKNOWN
        )


class TestPhraseMatching:
    def test_a_distinctive_name_resolves_outright(self, resolver: ScopeResolver) -> None:
        resolution = resolver.resolve("can we order some merch")
        assert resolution.outcome is Outcome.RESOLVED
        assert resolution.method == "phrase"
        assert resolution.item is not None
        assert resolution.item.item_id.endswith("--merch")

    def test_a_plural_request_finds_a_singular_name(self, resolver: ScopeResolver) -> None:
        assert resolver.resolve("billboards").items == resolver.resolve("billboard").items

    def test_a_common_name_does_not_settle_a_request(self, resolver: ScopeResolver) -> None:
        """The corpus contains a Copywriting item called simply "Emails".
        Matching it literally sent booking-flow requests to the copywriter."""
        resolution = resolver.resolve("set up emails for people who abandon their booking")
        assert resolution.method == "keyword"
        assert all(item.section != "Copywriting" for item in resolution.items)

    def test_the_longest_matching_phrase_wins(self, resolver: ScopeResolver) -> None:
        resolution = resolver.resolve("we want abandoned carts flows setting up")
        assert resolution.outcome is Outcome.RESOLVED
        assert resolution.item is not None
        assert "abandoned-carts" in resolution.item.item_id


class TestOutcomes:
    def test_candidates_that_agree_yield_a_verdict(self, resolver: ScopeResolver) -> None:
        """Billboards and Hoarding both need a quote. Asking which one is meant
        would be busywork, because the answer does not depend on it."""
        resolution = resolver.resolve("can we put an advert on a billboard")
        assert resolution.outcome is Outcome.AGREED
        assert len(resolution.candidates) > 1
        assert resolution.status is Status.QUOTE_REQUIRED
        assert resolution.question() is None

    def test_candidates_that_disagree_yield_no_verdict(self, resolver: ScopeResolver) -> None:
        """The whole point of the module. Where the choice changes the answer,
        only the user may make it."""
        resolution = resolver.resolve("can you translate our web pages into Spanish")
        assert resolution.outcome is Outcome.AMBIGUOUS
        assert resolution.status is None
        assert not resolution.decided
        assert len({item.status for item in resolution.items}) > 1

    def test_an_ambiguous_outcome_asks_a_real_question(self, resolver: ScopeResolver) -> None:
        resolution = resolver.resolve("can you translate our web pages into Spanish")
        question = resolution.question()
        assert question is not None
        for item in resolution.items:
            assert item.display_name in question

    def test_only_ambiguity_produces_a_question(self, resolver: ScopeResolver) -> None:
        assert resolver.resolve("merch").question() is None
        assert resolver.resolve("xyzzy plugh").question() is None

    def test_a_resolved_outcome_reports_the_corpus_wording(self, resolver: ScopeResolver) -> None:
        """Verdicts are described in the documents' own words so the corpus
        stays the single source of truth for how they are phrased."""
        resolution = resolver.resolve("merch")
        assert resolution.item is not None
        assert resolution.status_meaning == resolution.item.status_meaning
        assert resolution.status_meaning


class TestProvenance:
    def test_every_resolution_explains_itself(self, resolver: ScopeResolver) -> None:
        for query in ("merch", "translate our web pages", "xyzzy plugh"):
            assert resolver.resolve(query).explain()

    def test_the_method_is_always_recorded(self, resolver: ScopeResolver) -> None:
        assert resolver.resolve("merch").method == "phrase"
        assert resolver.resolve("I want to advertise on Google search").method == "keyword"

    def test_candidates_say_why_they_are_present(self, resolver: ScopeResolver) -> None:
        for candidate in resolver.resolve("can we put an advert on a billboard").candidates:
            assert candidate.reason

    def test_resolved_items_are_offered_to_retrieval(self, resolver: ScopeResolver) -> None:
        """A job cannot be done without the slice it is about, so the resolver
        hands retrieval the items it must include rather than hoping they
        score well enough to survive."""
        resolution = resolver.resolve("can we put an advert on a billboard")
        assert set(resolution.force_item_ids) == {item.item_id for item in resolution.items}

    def test_unknown_forces_nothing(self, resolver: ScopeResolver) -> None:
        assert resolver.resolve("xyzzy plugh").force_item_ids == ()


class TestSingleTermEvidence:
    """``_is_evidence`` decides whether a hit identifies a service or merely
    shares a word with one. Tested directly rather than through a corpus word,
    so the invariant does not depend on which words happen to be in the
    documents today — which is also why the document frequency is passed in."""

    RARE = 1
    """A word used by one document: naming it is a choice."""

    COMMON = 13
    """The frequency of "website", the word that once carried an in-scope
    verdict for a service this corpus does not offer."""

    @staticmethod
    def hit(matched: tuple[str, ...], coverage: float) -> ScoredChunk:
        chunk = Chunk(
            chunk_id="x:0",
            content="irrelevant",
            source="x.md",
            doc_type=DocType.SERVICE_ITEM,
            chunk_index=0,
            item_id="x",
        )
        return ScoredChunk(chunk, score=99.0, matched=matched, coverage=coverage)

    def test_one_rare_term_covering_the_name_is_evidence(self) -> None:
        assert _is_evidence(self.hit(("merch",), 1.0), self.RARE)

    def test_one_common_term_covering_the_name_is_not(self) -> None:
        """Coverage says the word fits the name; rarity says it was aimed
        there. "Build us a website from scratch" matched only "website", 59%
        of the alias "website content", and answered in scope free of charge
        for something the corpus does not offer."""
        assert not _is_evidence(self.hit(("website",), 0.59), self.COMMON)

    def test_one_term_covering_almost_none_of_the_name_is_not(self) -> None:
        """However high it scored, and however rare it is. A huge score on one
        incidental word is what the bare word "one" produced."""
        assert not _is_evidence(self.hit(("one",), 0.02), self.RARE)

    def test_two_terms_are_evidence_regardless_of_coverage(self) -> None:
        """Two independent words agreeing on the same item is a different kind
        of claim from one word appearing in it, so rarity is not consulted."""
        assert _is_evidence(self.hit(("photo", "booth"), 0.0), self.COMMON)

    def test_no_matched_terms_is_never_evidence(self) -> None:
        assert not _is_evidence(self.hit((), 0.0), self.RARE)


class TestBuildingAWebsiteIsNotAService:
    """The corpus has no "build a website" item, so the honest answer is that
    nothing matched. Kept as a resolver-level test because the failure was not
    a bad score — it was one generic noun clearing the evidence bar alone."""

    def test_it_names_no_service(self, resolver: ScopeResolver) -> None:
        resolution = resolver.resolve("can you build us a new website from scratch")
        assert resolution.outcome is Outcome.UNKNOWN
        assert resolution.status is None

    def test_a_one_word_request_for_a_real_service_still_works(
        self, resolver: ScopeResolver
    ) -> None:
        """The bar this raises must not take genuine short requests with it."""
        for request in ("merch", "billboards", "leaflets"):
            assert resolver.resolve(request).decided, request


def test_no_corpus_item_is_unreachable_by_its_own_name(corpus) -> None:
    """Every service must be findable by the name it is filed under. An item
    nobody can reach is a service Acme silently cannot be asked about."""
    chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
    resolver = ScopeResolver(corpus.catalog, InMemoryRetriever(KnowledgeIndex.build(chunks)))

    unreachable = [
        item.item_id
        for item in corpus.catalog
        if item.item_id
        not in resolver.resolve(item.item).force_item_ids
        and item.item_id not in resolver.resolve(item.display_name).force_item_ids
    ]
    assert not unreachable, f"unreachable by name: {unreachable}"


def test_a_verdict_is_never_stated_for_disagreeing_candidates(corpus) -> None:
    """Swept across every item name in the corpus, not just the eval cases."""
    chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
    resolver = ScopeResolver(corpus.catalog, InMemoryRetriever(KnowledgeIndex.build(chunks)))

    for item in corpus.catalog:
        resolution = resolver.resolve(item.display_name)
        if resolution.decided:
            verdicts = {candidate.item.status for candidate in resolution.candidates}
            assert len(verdicts) == 1, f"{item.item_id} produced a verdict from {verdicts}"


class TestACrowdedFieldIsTrimmedNotDiscarded:
    """More than ``MAX_CANDIDATES`` matches used to return UNKNOWN, on the
    reasoning that a long menu is a wall rather than a question. True of what
    gets shown, but it threw the leader away with the noise."""

    def test_a_confident_leader_survives_a_crowd(self, resolver: ScopeResolver) -> None:
        resolution = resolver.resolve("new graphics for our in-venue screens")
        assert resolution.outcome is not Outcome.UNKNOWN
        assert resolution.candidates[0].item.item_id == (
            "renders-and-other-designs-for-venue-exteriors--graphics-for-screens"
        )

    def test_a_question_never_offers_more_than_max_candidates(
        self, corpus, resolver: ScopeResolver
    ) -> None:
        """Trimming protects the reply, and must not be bypassable.

        Only questions are capped. An AGREED outcome may rest on any number of
        candidates because it shows none of them: they all carry the same
        verdict, and that verdict is the whole answer.
        """
        for item in corpus.catalog:
            resolution = resolver.resolve(item.display_name)
            if resolution.outcome is not Outcome.AMBIGUOUS:
                continue
            assert len(resolution.candidates) <= MAX_CANDIDATES, item.item_id
            question = resolution.question() or ""
            assert question.count("\n") <= MAX_CANDIDATES, item.item_id


class TestTheDisagreementGuardNeedsCorroboration:
    """The guard promotes a rival the request named. Naming is necessary but
    not sufficient: words appear in sentences for reasons of their own."""

    def test_a_station_name_is_not_a_request_for_radio_ads(
        self, resolver: ScopeResolver
    ) -> None:
        """"Heart Radio" is a station. Without embeddings this still asks -
        keyword scoring cannot tell a second reading from a shared word, and
        asking is the safe direction - but it must never state the wrong
        verdict, and Campaign wrap-ups must remain the leading candidate."""
        resolution = resolver.resolve(
            "can we get a wrap-up on how the Heart Radio campaign performed"
        )
        assert resolution.candidates
        assert resolution.candidates[0].item.item_id == (
            "analytics-tracking-dashboards--campaign-wrap-ups"
        )
        assert resolution.status is not Status.QUOTE_REQUIRED

    def test_two_services_that_are_both_named_still_ask(
        self, resolver: ScopeResolver
    ) -> None:
        """The case the guard exists for, and the ruling it encodes: when a
        request genuinely names two services that are handled differently, the
        choice belongs to the user. Web pages is free of charge; Translation &
        localisation belongs to the local team."""
        resolution = resolver.resolve("do you handle translating our web pages")
        assert resolution.outcome is Outcome.AMBIGUOUS
        assert resolution.status is None
        named = {candidate.item.item_id for candidate in resolution.candidates}
        assert "copywriting--translation-localisation" in named


class _FixedRetriever:
    """Returns exactly the ranking a test sets up, as retrieval would.

    The costlier-lookalike guard runs only on semantic retrieval, and turns on
    confidences and matched words the keyword index in these tests cannot be
    made to produce on demand. So the ranking is stated outright, sorted by
    confidence the way the real retriever sorts it, and truncated to the limit
    asked for — which is also the property that lets the guard read further
    down than the admission rules without changing what they see.
    """

    def __init__(self, hits: list[ScoredChunk], mode: str = "keyword+dense") -> None:
        self._hits = sorted(hits, key=lambda hit: hit.confidence, reverse=True)
        self._mode = mode

    def retrieve(self, query: str, *, limit: int = 5, **_: object) -> RetrievalResult:
        return RetrievalResult(hits=tuple(self._hits[:limit]), mode=self._mode)


EMAILS = "copywriting--emails"
AD_HOC = "email-marketing-sms--ad-hoc-email-requests-typically-4-5-per-month"
AUTOMATION = "email-marketing-sms--automation-of-all-other-flows-i-e-vouchers-and-birthdays"
TRANSACTIONAL = "email-marketing-sms--transactional-sms-emails"
TEMPLATES = "email-marketing-sms--email-template-creation"
PROMOTIONAL = "email-marketing-sms--promotional-campaign-planning-sms-email"
RADIO_ADS = "renders-and-other-designs-for-venue-exteriors--radio-ads"

# Words no document declares as a name, so the phrase path never settles the
# request and every decision below comes from the ranking the test supplies.
UNNAMED = "flurbish gronkle"


def _scored(item_id: str, confidence: float, *matched: str) -> ScoredChunk:
    chunk = Chunk(
        chunk_id=f"{item_id}:0",
        content="irrelevant",
        source=f"{item_id}.md",
        doc_type=DocType.SERVICE_ITEM,
        chunk_index=0,
        item_id=item_id,
    )
    return ScoredChunk(
        chunk, score=confidence * 3, matched=matched, coverage=0.5, confidence=confidence
    )


def _resolve(corpus, hits: list[ScoredChunk], mode: str = "keyword+dense"):
    return ScopeResolver(corpus.catalog, _FixedRetriever(hits, mode)).resolve(UNNAMED)


class TestAWeakFreeVerdictIsQuestionedWhenACostlierServiceReadsAlike:
    """Reported live: "I need to send an email about an upcoming event" was
    answered Emails (Copywriting), no extra cost, while Ad hoc email requests —
    which needs a quote and lists event invitations as an example — sat just
    below the confidence floor and was never looked at."""

    def test_the_live_case_is_put_to_the_user(self, corpus) -> None:
        resolution = _resolve(corpus, [
            _scored(EMAILS, 0.57, "send", "email"),
            _scored(AUTOMATION, 0.48, "send", "email"),
            _scored(PROMOTIONAL, 0.46, "send", "email"),
            _scored(AD_HOC, 0.435, "email", "event"),
        ])
        assert resolution.outcome is Outcome.AMBIGUOUS
        assert resolution.status is None, "no verdict may be stated"
        offered = [candidate.item.item_id for candidate in resolution.candidates]
        assert offered[0] == EMAILS, "the leader still leads"
        assert AD_HOC in offered
        assert resolution.method.endswith("+lookalike")

    def test_a_service_that_only_shares_a_stray_word_is_not_raised(self, corpus) -> None:
        """Heart Radio campaign wrap-up: Radio ads came within reach on the word
        radio alone. It shares nothing with what made the leader lead, so it is
        a different subject, not a second reading of this one."""
        resolution = _resolve(corpus, [
            _scored(EMAILS, 0.60, "campaign", "wrap"),
            _scored(RADIO_ADS, 0.47, "radio", "advert"),
        ])
        assert resolution.outcome is Outcome.RESOLVED
        assert resolution.status is Status.IN_SCOPE

    def test_a_strong_free_verdict_stands(self, corpus) -> None:
        resolution = _resolve(corpus, [
            _scored(EMAILS, 0.85, "write", "email"),
            _scored(AD_HOC, 0.70, "email", "event"),
        ])
        assert resolution.outcome is Outcome.RESOLVED

    def test_a_distant_lookalike_is_not_raised(self, corpus) -> None:
        resolution = _resolve(corpus, [
            _scored(EMAILS, 0.60, "send", "email"),
            _scored(AD_HOC, 0.40, "email", "event"),
        ])
        assert resolution.outcome is Outcome.RESOLVED

    def test_only_a_free_verdict_is_questioned(self, corpus) -> None:
        """One-directional. Calling a chargeable service free costs money when
        the invoice arrives; the reverse costs a conversation."""
        # The free service sits where it would raise a question under a free
        # leader — close, sharing "email" — but below the ordinary rival floor,
        # so nothing except this guard could turn it into one.
        resolution = _resolve(corpus, [
            _scored(AD_HOC, 0.60, "email", "event"),
            _scored(EMAILS, 0.48, "send", "email"),
        ])
        assert resolution.outcome is Outcome.RESOLVED
        assert resolution.status is Status.QUOTE_REQUIRED

    def test_keyword_scores_alone_do_not_trigger_it(self, corpus) -> None:
        """Offline the populations overlap: the same rule would question a
        request for the marketing calendar and still answer an email case. So
        without embeddings the resolver keeps its old behaviour."""
        ranking = [_scored(EMAILS, 0.57, "send", "email"), _scored(AD_HOC, 0.45, "email", "event")]
        # The same ranking, so the mode is the only thing that differs.
        assert _resolve(corpus, ranking, mode="keyword").outcome is Outcome.RESOLVED
        assert _resolve(corpus, ranking).outcome is Outcome.AMBIGUOUS

    def test_an_agreed_answer_is_questioned_too(self, corpus) -> None:
        """The most dangerous variant. Can you send an email for our event agreed
        on two free services and answered without asking at all."""
        resolution = _resolve(corpus, [
            _scored(EMAILS, 0.68, "send", "email"),
            _scored(AUTOMATION, 0.60, "send", "email"),
            _scored(AD_HOC, 0.54, "email", "event"),
        ])
        assert resolution.outcome is Outcome.AMBIGUOUS
        assert resolution.method.endswith("+lookalike"), "the ordinary rules agreed"
        assert AD_HOC in {candidate.item.item_id for candidate in resolution.candidates}

    def test_the_lookalike_survives_trimming_a_crowded_agreement(self, corpus) -> None:
        """Four free services agreeing plus one lookalike is five options.
        Trimmed from the end, the one option that makes it a question would be
        the one dropped, leaving a question about four things that agree."""
        resolution = _resolve(corpus, [
            _scored(EMAILS, 0.70, "send", "email"),
            _scored(AUTOMATION, 0.66, "send", "email"),
            _scored(TRANSACTIONAL, 0.64, "send", "email"),
            _scored(TEMPLATES, 0.62, "send", "email"),
            _scored(AD_HOC, 0.55, "email", "event"),
        ])
        assert resolution.outcome is Outcome.AMBIGUOUS
        assert resolution.method.endswith("+lookalike")
        offered = [candidate.item.item_id for candidate in resolution.candidates]
        assert len(offered) == MAX_CANDIDATES
        assert AD_HOC in offered

    def test_it_reads_past_the_hits_the_admission_rules_keep(self, corpus) -> None:
        """In the live case the quoted service was fifth of six. The admission
        rules still see only the first MAX_CANDIDATES + 1; a hit further down
        must be able to raise the question without becoming a contender."""
        resolution = _resolve(corpus, [
            _scored(EMAILS, 0.60, "send", "email"),
            _scored(AUTOMATION, 0.49, "send", "email"),
            _scored(TRANSACTIONAL, 0.48, "send", "email"),
            _scored(TEMPLATES, 0.47, "send", "email"),
            _scored(PROMOTIONAL, 0.46, "send", "email"),
            _scored(AD_HOC, 0.45, "email", "event"),
        ])
        offered = [candidate.item.item_id for candidate in resolution.candidates]
        assert resolution.outcome is Outcome.AMBIGUOUS
        assert resolution.method.endswith("+lookalike")
        assert offered[:2] == [EMAILS, AD_HOC]
