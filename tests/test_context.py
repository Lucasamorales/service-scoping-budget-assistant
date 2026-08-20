"""Invariants of the system prompt and of the facts the model is shown.

What the model is shown decides what it can say, so these assert the shape of
that material rather than any wording. The central property: when the resolver
could not reach a verdict, the briefing must actively forbid inventing one, not
merely omit it.

These used to target ``build_context``/``ContextPack``. That prompt assembly was
replaced by ``FactPack.briefing()`` during the plan-execute-compose refactor, so
the invariants now run against the live path — ``Pipeline.prepare()`` — which is
what the deployed service actually builds.
"""

from __future__ import annotations

import pytest

from app.knowledge.chunking import chunk_service_item
from app.knowledge.index import KnowledgeIndex
from app.orchestrator.context import load_system_prompt
from app.orchestrator.pipeline import Pipeline

load_system_prompt.cache_clear()


def test_system_prompt_includes_acme_tone_of_voice() -> None:
    """Brand voice is meta: always on, never cited as evidence."""
    load_system_prompt.cache_clear()
    prompt = load_system_prompt()
    assert "approachable" in prompt.lower()
    assert "Tone & Voice" in prompt or "tone of voice" in prompt.lower()
    assert "conversation" in prompt.lower()


@pytest.fixture(scope="module")
def pipeline(corpus):
    """The real pipeline, with no model — briefings do not need one."""
    chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
    return Pipeline(corpus.catalog, KnowledgeIndex.build(chunks), model=None)


def briefing(pipeline: Pipeline, question: str) -> str:
    """What the model would be told for this question."""
    return pipeline.prepare(question).briefing()


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


class TestVerdict:
    def test_a_resolved_verdict_is_stated_as_fact(self, pipeline) -> None:
        text = briefing(pipeline, "can we order some merch")
        assert "Verdict" in text
        assert "do not reinterpret it" in text.lower()

    def test_a_resolved_verdict_uses_the_corpus_wording(self, pipeline) -> None:
        assert "This is something we need to quote" in briefing(
            pipeline, "can we order some merch"
        )

    def test_agreed_candidates_are_all_named_and_not_put_to_the_user(self, pipeline) -> None:
        """Both Billboards and Hoarding need a quote, so asking which is meant
        would be busywork."""
        text = briefing(pipeline, "can we put an advert on a billboard")
        assert "Billboards" in text
        assert "Hoarding" in text
        assert "do not ask them to choose" in text.lower()

    def test_ambiguity_forbids_a_verdict_rather_than_omitting_one(self, pipeline) -> None:
        """The whole design in one assertion. Leaving the verdict out would
        invite the model to supply one from the documents it can see."""
        text = briefing(pipeline, "can you translate our web pages into Spanish")
        assert "No verdict" in text
        assert "state no verdict" in text.lower()
        assert "hint at none" in text.lower()

    def test_an_unmatched_request_forbids_guessing(self, pipeline) -> None:
        text = briefing(pipeline, "can we hire a hot air balloon for the weekend")
        assert "No verdict" in text or "No facts were found" in text
        assert "do not guess" in text.lower()

    def test_a_handover_suppresses_the_substance(self, pipeline) -> None:
        """A plausible answer about photography here would be grotesque."""
        text = briefing(
            pipeline, "someone was injured during the photo shoot, can we use the photos"
        )
        assert "Hand this to a person" in text
        assert "do not answer the question" in text.lower()

    def test_a_handover_carries_no_evidence(self, pipeline) -> None:
        turn = pipeline.prepare("a customer is threatening legal action")
        assert turn.facts.evidence == ()
        assert "Supporting documents" not in turn.briefing()


class TestEvidence:
    def test_evidence_reaches_the_briefing(self, pipeline) -> None:
        turn = pipeline.prepare("can we order some merch")
        assert turn.facts.evidence
        assert turn.facts.evidence[0].content in turn.briefing()

    def test_the_verdict_precedes_the_evidence(self, pipeline) -> None:
        """It is the conclusion; the documents only explain it."""
        text = briefing(pipeline, "can we order some merch")
        assert text.index("Verdict") < text.index("Supporting documents")

    def test_documents_are_told_not_to_override_the_verdict(self, pipeline) -> None:
        assert "never override the verdict" in briefing(
            pipeline, "can we order some merch"
        ).lower()

    def test_the_question_survives_to_the_model(self, pipeline) -> None:
        from app.orchestrator.wording import build_briefing

        turn = pipeline.prepare("can we order some merch")
        assert "can we order some merch" in build_briefing(
            turn.facts, turn.route.message
        )


class TestCitations:
    def test_citations_always_exist(self, pipeline) -> None:
        """Even 'nothing was retrieved' is a citation. The alternative is an
        answer whose basis nobody can check."""
        for question in ("can we order some merch", "a customer is threatening legal action"):
            assert pipeline.prepare(question).citations

    def test_the_document_the_resolver_required_is_cited_first(self, pipeline) -> None:
        """The service the verdict came from leads, so the basis of the answer is
        the first thing a reader checks."""
        turn = pipeline.prepare("can we order some merch")
        assert turn.citations[0] == "Merch"


def test_no_question_ever_produces_a_briefing_without_an_instruction(pipeline) -> None:
    """Swept across every outcome. A briefing with evidence but no instruction
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
        text = briefing(pipeline, question)
        assert text.strip()
        # Every branch either states a verdict, refuses one, or hands over —
        # none of them leaves the model to decide for itself.
        assert any(
            marker in text
            for marker in (
                "Verdict",
                "No verdict",
                "No facts were found",
                "Hand this to a person",
                "service catalog",
                "What you can do for this person",
            )
        ), question
