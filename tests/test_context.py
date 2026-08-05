"""Invariants of the assembled prompt.

What the model is shown decides what it can say, so these assert the shape of
that material rather than any wording. The central property: when the resolver
could not reach a verdict, the prompt must actively forbid inventing one, not
merely omit it.

Also exercises the full pipeline - route, resolve, retrieve, assemble - across
every outcome, since that path is what the deployed service runs.
"""

from __future__ import annotations

import pytest

from app.knowledge.chunking import chunk_service_item
from app.knowledge.index import KnowledgeIndex
from app.knowledge.retriever import InMemoryRetriever, RetrievalResult
from app.orchestrator.context import (
    ContextPack,
    build_context,
    estimate_tokens,
    load_system_prompt,
)
from app.orchestrator.resolver import Outcome, Resolution, ScopeResolver
from app.orchestrator.router import ConversationState, Intent, Router

EVIDENCE_LIMIT = 4


@pytest.fixture(scope="module")
def pipeline(corpus):
    chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
    retriever = InMemoryRetriever(KnowledgeIndex.build(chunks))
    return Router(), ScopeResolver(corpus.catalog, retriever), retriever


def ask(pipeline, question: str, state: ConversationState | None = None) -> ContextPack:
    router, resolver, retriever = pipeline
    route = router.route(question, state or ConversationState())

    if route.intent is Intent.HANDOVER:
        return build_context(route, Resolution(Outcome.UNKNOWN, question), RetrievalResult())

    resolution = resolver.resolve(question)
    retrieval = retriever.retrieve(
        question, limit=EVIDENCE_LIMIT, force_item_ids=resolution.force_item_ids
    )
    return build_context(route, resolution, retrieval)


class TestSystemPrompt:
    def test_the_prompt_loads_from_disk(self) -> None:
        assert len(load_system_prompt()) > 500

    def test_an_unreadable_prompt_raises_rather_than_defaulting(self, tmp_path) -> None:
        """A model with no instructions is far more dangerous than one that
        refuses to start."""
        with pytest.raises(OSError):
            load_system_prompt(tmp_path / "missing.md")

    def test_the_prompt_forbids_inventing_prices(self) -> None:
        assert "invent" in load_system_prompt().lower()

    def test_the_prompt_states_that_verdicts_are_given_not_decided(self) -> None:
        assert "Never decide it yourself" in load_system_prompt()


class TestVerdictBlock:
    def test_a_resolved_verdict_is_stated_as_fact(self, pipeline) -> None:
        pack = ask(pipeline, "can we order some merch")
        assert "AUTHORITATIVE VERDICT" in pack.verdict_block
        assert "Do not reinterpret it" in pack.verdict_block

    def test_a_resolved_verdict_uses_the_corpus_wording(self, pipeline) -> None:
        pack = ask(pipeline, "can we order some merch")
        assert "This is something we need to quote" in pack.verdict_block

    def test_agreed_candidates_are_all_named_and_not_put_to_the_user(self, pipeline) -> None:
        """Both Billboards and Hoarding need a quote, so asking which is meant
        would be busywork."""
        pack = ask(pipeline, "can we put an advert on a billboard")
        assert "Billboards" in pack.verdict_block
        assert "Hoarding" in pack.verdict_block
        assert "do not ask the user to choose" in pack.verdict_block

    def test_ambiguity_forbids_a_verdict_rather_than_omitting_one(self, pipeline) -> None:
        """The whole design in one assertion. Leaving the verdict out would
        invite the model to supply one from the documents it can see."""
        pack = ask(pipeline, "can you translate our web pages into Spanish")
        assert "NO VERDICT" in pack.verdict_block
        assert "Do not state a verdict" in pack.verdict_block
        assert "do not hint at one" in pack.verdict_block

    def test_an_unmatched_request_forbids_guessing(self, pipeline) -> None:
        pack = ask(pipeline, "can we hire a hot air balloon for the weekend")
        assert "NO VERDICT" in pack.verdict_block
        assert "Do not guess" in pack.verdict_block

    def test_a_handover_suppresses_the_substance(self, pipeline) -> None:
        """A plausible answer about photography here would be grotesque."""
        pack = ask(pipeline, "someone was injured during the photo shoot, can we use the photos")
        assert "HANDOVER" in pack.verdict_block
        assert "do not answer the underlying question" in pack.verdict_block.lower()

    def test_a_handover_retrieves_nothing(self, pipeline) -> None:
        pack = ask(pipeline, "a customer is threatening legal action")
        assert pack.evidence == ()


class TestEvidenceAndBudget:
    def test_evidence_reaches_the_prompt(self, pipeline) -> None:
        pack = ask(pipeline, "can we order some merch")
        assert pack.evidence
        assert pack.evidence[0].content in pack.as_prompt()

    def test_the_verdict_precedes_the_evidence(self, pipeline) -> None:
        """It is the conclusion; the documents only explain it."""
        prompt = ask(pipeline, "can we order some merch").as_prompt()
        assert prompt.index("AUTHORITATIVE VERDICT") < prompt.index("Supporting documents")

    def test_trimming_is_reported_rather_than_silent(self, pipeline) -> None:
        router, resolver, retriever = pipeline
        route = router.route("marketing")
        resolution = resolver.resolve("marketing")
        retrieval = retriever.retrieve("marketing", limit=5)

        pack = build_context(route, resolution, retrieval, budget=400)
        assert pack.dropped
        assert any("left out" in note for note in pack.notes)
        assert "may be incomplete" in pack.as_prompt()

    def test_at_least_one_document_survives_any_budget(self, pipeline) -> None:
        router, resolver, retriever = pipeline
        route = router.route("merch")
        resolution = resolver.resolve("merch")
        retrieval = retriever.retrieve("merch", limit=3)

        pack = build_context(route, resolution, retrieval, budget=1)
        assert len(pack.evidence) == 1

    def test_a_verdict_with_no_evidence_is_flagged(self, pipeline) -> None:
        router, resolver = pipeline[0], pipeline[1]
        route = router.route("merch")
        resolution = resolver.resolve("merch")

        pack = build_context(route, resolution, RetrievalResult())
        assert any("no supporting text" in note for note in pack.notes)

    def test_token_estimation_scales_with_length(self) -> None:
        assert estimate_tokens("word " * 100) > estimate_tokens("word " * 10)
        assert estimate_tokens("") == 0


class TestCitations:
    def test_citations_always_exist(self, pipeline) -> None:
        """Even 'nothing was retrieved' is a citation. The alternative is an
        answer whose basis nobody can check."""
        for question in ("can we order some merch", "a customer is threatening legal action"):
            assert ask(pipeline, question).citations

    def test_forced_documents_are_marked_as_such(self, pipeline) -> None:
        pack = ask(pipeline, "can we order some merch")
        assert any("required by the resolver" in citation for citation in pack.citations)

    def test_citations_match_the_evidence_sent(self, pipeline) -> None:
        pack = ask(pipeline, "can we put an advert on a billboard")
        assert len(pack.citations) == len(pack.evidence)


def test_no_question_ever_produces_a_prompt_without_a_verdict_block(pipeline) -> None:
    """Swept across every outcome. A prompt with evidence but no instruction
    about what may be concluded from it is exactly how a model ends up
    inventing a verdict."""
    questions = (
        "can we order some merch",
        "can we put an advert on a billboard",
        "can you translate our web pages into Spanish",
        "can we hire a hot air balloon",
        "someone was injured",
        "",
        "???",
    )
    for question in questions:
        pack = ask(pipeline, question)
        assert pack.verdict_block
        assert pack.verdict_block in pack.as_prompt()
        assert pack.system_prompt in pack.as_prompt()
