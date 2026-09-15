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

    def test_the_item_the_resolver_required_is_described_first(self, pipeline) -> None:
        """The service the verdict came from leads, so the basis of the answer is
        the first thing a reader checks."""
        turn = pipeline.prepare("can we order some merch")
        assert turn.citations[0].startswith("Merch includes")

    def test_the_citation_says_what_the_item_is_not_what_it_is_called(
        self, pipeline
    ) -> None:
        """The name is already on the verdict badge above it. Repeating it there
        told a reader nothing they could not see; a sentence from the
        documentation is how they tell Billboards from Hoarding."""
        (citation,) = pipeline.prepare("can we order some merch").citations
        assert len(citation.split()) > 5
        assert citation.endswith((".", "…"))

    def test_rejected_candidates_are_never_cited(self, pipeline) -> None:
        """The line used to be built from the whole retrieval shortlist, so it
        named services the resolver had considered and thrown away — sources the
        answer did not come from, which is worse than citing nothing."""
        turn = pipeline.prepare("can we put an advert on a billboard")
        assert len(turn.citations) == 1


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


class TestANoPointsSomewhereReal:
    """A verdict that leaves central marketing nothing to do still needs a next
    step, or the model invents one. "QR code reports" came back out of scope with
    a suggestion to chat to "your project manager", a role these venues do not
    have, wrapped in "Unfortunately... it would need extra resources we don't
    currently have"."""

    OUT = "can someone send me the QR report"
    LOCAL = "who looks after our instagram posts"

    def test_an_out_of_scope_briefing_offers_to_reach_the_account_manager(
        self, pipeline
    ) -> None:
        """It used to point them to the Account Manager in words only. The ask
        was for the assistant to put them in touch, so the briefing now carries
        an offer to email the Account Manager, and no competing next step."""
        text = briefing(pipeline, self.OUT)
        assert "Status code: out_of_scope" in text
        assert "## The next step you are offering" in text
        assert "email their Account Manager, who might still find another way to help" in text
        assert "Next step: point them to" not in text

    def test_an_out_of_scope_briefing_asks_for_a_plain_no(self, pipeline) -> None:
        from app.orchestrator.facts import NOT_COVERED

        text = briefing(pipeline, self.OUT)
        assert NOT_COVERED in text
        assert "Give no reason, no apology" in text
        assert "right now" in text, "the time words are named so they are avoided"

    def test_a_local_briefing_names_the_local_team(self, pipeline) -> None:
        text = briefing(pipeline, self.LOCAL)
        assert "Status code: local" in text
        assert "Next step: point them to their local site or operations team" in text

    def test_the_no_guidance_is_only_for_out_of_scope(self, pipeline) -> None:
        """Local is not a no from anyone; the local team does the work. Telling
        the model to withhold the reason there would withhold the answer."""
        assert "This is a no from central marketing" not in briefing(pipeline, self.LOCAL)

    def test_an_answer_with_its_own_offer_gets_no_competing_next_step(
        self, pipeline
    ) -> None:
        """In scope and quote required carry an email offer. A second next step
        beside it would leave the reader choosing between two."""
        assert "Next step:" not in briefing(pipeline, "can we order some merch")

    def test_the_old_instruction_that_made_a_no_cold_is_gone(self, pipeline) -> None:
        assert "do not soften a no" not in briefing(pipeline, self.OUT)


class TestTheReplyWithoutAModelPointsSomewhereReal:
    """The deterministic reply is what ships when the model is off or its reply
    is rejected. It follows the same table the model is briefed from."""

    def test_out_of_scope_routes_to_the_account_manager(self, pipeline) -> None:
        text = pipeline.answer("can someone send me the QR report").text
        assert "Account Manager" in text
        assert "project manager" not in text.lower()

    def test_out_of_scope_gives_no_reason(self, pipeline) -> None:
        text = pipeline.answer("can someone send me the QR report").text
        assert "resources" not in text.lower()

    def test_local_routes_to_the_local_team(self, pipeline) -> None:
        text = pipeline.answer("who looks after our instagram posts").text
        assert "local site or operations team" in text
