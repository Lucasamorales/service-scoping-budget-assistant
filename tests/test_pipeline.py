"""End to end turns, and the conversation between them.

The property these exist to defend: **the verdict does not depend on the
model.** Gemini improves the wording and nothing else, so the same question
must produce the same scope answer whether the model is present, absent or
broken.
"""

from __future__ import annotations

import pytest

from app.core.types import Status
from app.knowledge.chunking import chunk_service_item
from app.knowledge.index import KnowledgeIndex
from app.orchestrator.llm import DETERMINISTIC, ModelReply
from app.orchestrator.pipeline import Pipeline
from app.orchestrator.resolver import Outcome
from app.orchestrator.router import ConversationState, Intent


class RecordingModel:
    """A model that always answers, and remembers what it was asked."""

    def __init__(self, text: str = "A polished reply.") -> None:
        self.text = text
        self.prompts: list[str] = []

    @property
    def name(self) -> str:
        return "recording-model"

    def generate(self, prompt: str) -> ModelReply:
        self.prompts.append(prompt)
        return ModelReply(self.text, self.name)


class BrokenModel:
    """A model that is configured but cannot be reached."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "broken-model"

    def generate(self, prompt: str) -> ModelReply:
        self.calls += 1
        return ModelReply("", self.name, degraded=True, error="connection refused")


class EmptyModel:
    """A model that returns nothing, as safety filters and token limits do."""

    @property
    def name(self) -> str:
        return "empty-model"

    def generate(self, prompt: str) -> ModelReply:
        return ModelReply("   ", self.name)


@pytest.fixture(scope="module")
def index(corpus) -> KnowledgeIndex:
    chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
    return KnowledgeIndex.build(chunks)


@pytest.fixture
def pipeline(corpus, index) -> Pipeline:
    return Pipeline(corpus.catalog, index)


def with_model(corpus, index, model) -> Pipeline:
    return Pipeline(corpus.catalog, index, model=model)


class TestWithoutAModel:
    def test_a_scoping_question_is_answered(self, pipeline: Pipeline) -> None:
        answer = pipeline.answer("can we order some merch")
        assert answer.status is Status.QUOTE_REQUIRED
        assert answer.source == DETERMINISTIC
        assert not answer.degraded

    def test_the_answer_states_the_verdict_in_the_corpus_wording(
        self, pipeline: Pipeline
    ) -> None:
        answer = pipeline.answer("can we order some merch")
        assert "we need to quote" in answer.text

    def test_agreed_candidates_produce_one_answer_not_a_question(
        self, pipeline: Pipeline
    ) -> None:
        answer = pipeline.answer("can we put an advert on a billboard")
        assert answer.resolution.outcome is Outcome.AGREED
        assert answer.status is Status.QUOTE_REQUIRED
        assert not answer.awaiting_answer

    def test_ambiguity_asks_and_states_no_verdict(self, pipeline: Pipeline) -> None:
        answer = pipeline.answer("can you translate our web pages into Spanish")
        assert answer.status is None
        assert answer.awaiting_answer
        assert "Which do you mean" in answer.text

    def test_an_unmatched_request_admits_it(self, pipeline: Pipeline) -> None:
        answer = pipeline.answer("can we hire a hot air balloon for the weekend")
        assert answer.status is None
        assert "could not tell which service" in answer.text

    def test_every_answer_cites_something(self, pipeline: Pipeline) -> None:
        for question in ("merch", "someone was injured", "hot air balloon", "hello"):
            assert pipeline.answer(question).citations


class TestHandover:
    def test_a_handover_gives_the_reason_and_nothing_else(self, pipeline: Pipeline) -> None:
        answer = pipeline.answer("a customer is threatening legal action over their booking")
        assert answer.needs_a_human
        assert "legal" in answer.text.lower()
        assert answer.status is None

    def test_a_handover_never_reaches_the_model(self, corpus, index) -> None:
        """Two reasons. The wording is fixed and has been reviewed, and a model
        given an injury to discuss might discuss it."""
        model = RecordingModel()
        answer = with_model(corpus, index, model).answer("someone was injured in the branch")
        assert model.prompts == []
        assert answer.source == DETERMINISTIC

    def test_a_handover_retrieves_nothing(self, pipeline: Pipeline) -> None:
        *_, pack = pipeline.prepare("someone was injured in the branch")
        assert pack.evidence == ()


class TestWithAModel:
    def test_the_model_writes_the_reply(self, corpus, index) -> None:
        model = RecordingModel("Yes, that one needs a quote first.")
        answer = with_model(corpus, index, model).answer("can we order some merch")
        assert answer.text == "Yes, that one needs a quote first."
        assert answer.source == "recording-model"

    def test_the_model_is_given_the_verdict_not_asked_for_one(self, corpus, index) -> None:
        model = RecordingModel()
        with_model(corpus, index, model).answer("can we order some merch")
        assert "AUTHORITATIVE VERDICT" in model.prompts[0]
        assert "we need to quote" in model.prompts[0]

    def test_the_verdict_is_unchanged_by_the_model(self, corpus, index, pipeline) -> None:
        """The property this whole design exists for. Wording may differ; scope
        may not."""
        questions = (
            "can we order some merch",
            "can we put an advert on a billboard",
            "can you translate our web pages into Spanish",
            "can we hire a hot air balloon",
        )
        with_a_model = with_model(corpus, index, RecordingModel())
        for question in questions:
            assert pipeline.answer(question).status == with_a_model.answer(question).status

    def test_a_broken_model_falls_back_and_admits_it(self, corpus, index) -> None:
        model = BrokenModel()
        answer = with_model(corpus, index, model).answer("can we order some merch")
        assert model.calls == 1
        assert answer.degraded
        assert answer.source == DETERMINISTIC
        assert answer.status is Status.QUOTE_REQUIRED

    def test_an_empty_completion_is_treated_as_a_failure(self, corpus, index) -> None:
        """Safety filters and token exhaustion both return nothing. Showing a
        blank reply would look like the assistant had no answer."""
        answer = with_model(corpus, index, EmptyModel()).answer("can we order some merch")
        assert answer.degraded
        assert answer.text.strip()


class TestConversation:
    def test_a_clarifying_question_can_be_answered_by_number(self, pipeline: Pipeline) -> None:
        first = pipeline.answer("can you translate our web pages into Spanish")
        assert first.awaiting_answer

        second = pipeline.answer("the second one", first.next_state)
        assert second.route.intent is Intent.CLARIFICATION_REPLY
        assert second.status is not None
        assert not second.awaiting_answer

    def test_answering_resolves_to_the_chosen_service(self, pipeline: Pipeline) -> None:
        first = pipeline.answer("can you translate our web pages into Spanish")
        chosen = first.resolution.force_item_ids[1]

        second = pipeline.answer("the second one", first.next_state)
        assert second.resolution.force_item_ids[0] == chosen

    def test_a_bare_follow_up_keeps_the_previous_subject(self, pipeline: Pipeline) -> None:
        first = pipeline.answer("can we order some merch")
        second = pipeline.answer("and for Bedford?", first.next_state)
        assert second.route.intent is Intent.FOLLOW_UP
        assert second.status is first.status

    def test_a_follow_up_that_names_a_service_is_about_that_service(
        self, pipeline: Pipeline
    ) -> None:
        """Regression. Carrying the previous subject into every follow-up meant
        "and what about merch" was answered about the *previous* service. Both
        messages are follow-ups; only one of them lacks a subject."""
        first = pipeline.answer("can you translate our web pages into Spanish")
        second = pipeline.answer("and what about merch", first.next_state)

        merch = [
            item_id for item_id in second.resolution.force_item_ids if item_id.endswith("merch")
        ]
        assert merch, second.resolution.explain()
        assert second.resolution.force_item_ids != first.resolution.force_item_ids

    def test_context_is_only_borrowed_when_the_message_needs_it(
        self, pipeline: Pipeline
    ) -> None:
        first = pipeline.answer("can we order some merch")
        named = pipeline.answer("and what about an SEO audit", first.next_state)
        assert named.resolution.force_item_ids != first.resolution.force_item_ids

    def test_a_fresh_question_drops_the_previous_subject(self, pipeline: Pipeline) -> None:
        first = pipeline.answer("can we order some merch")
        second = pipeline.answer("what about an SEO audit", first.next_state)
        assert second.resolution.force_item_ids != first.resolution.force_item_ids

    def test_a_handover_mid_conversation_still_wins(self, pipeline: Pipeline) -> None:
        first = pipeline.answer("can you translate our web pages into Spanish")
        second = pipeline.answer("actually someone got injured", first.next_state)
        assert second.needs_a_human

    def test_state_is_carried_without_the_caller_assembling_it(
        self, pipeline: Pipeline
    ) -> None:
        answer = pipeline.answer("can we order some merch")
        assert isinstance(answer.next_state, ConversationState)
        assert answer.next_state.last_item_ids


class TestDegradedStartup:
    def test_it_answers_with_no_index_at_all(self, corpus) -> None:
        """A missing artifact costs paraphrase handling, not verdicts: names
        and aliases still resolve straight from the catalog."""
        pipeline = Pipeline(corpus.catalog, KnowledgeIndex())
        answer = pipeline.answer("merch")
        assert answer.status is Status.QUOTE_REQUIRED

    def test_a_paraphrase_without_an_index_is_admitted_not_guessed(self, corpus) -> None:
        pipeline = Pipeline(corpus.catalog, KnowledgeIndex())
        assert pipeline.answer("something to hand out at reception").status is None


def test_no_answer_ever_mentions_a_price(pipeline: Pipeline) -> None:
    """Nothing in the corpus carries a number, so nothing downstream may
    produce one. The deterministic path is the one that could leak a figure by
    accident, since it assembles text from the documents directly."""
    forbidden = ("£", "$", "€", "per day", "day rate")
    questions = (
        "can we order some merch",
        "how much is a billboard",
        "what would venue photos cost",
        "can we put an advert on a billboard",
    )
    for question in questions:
        text = pipeline.answer(question).text.lower()
        assert not any(token in text for token in forbidden), question
