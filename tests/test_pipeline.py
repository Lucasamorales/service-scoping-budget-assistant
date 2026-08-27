"""End to end turns, and the conversation between them.

The property these exist to defend: **the verdict does not depend on the
model.** Gemini improves the wording and nothing else, so the same question
must produce the same scope answer whether the model is present, absent or
broken.
"""

from __future__ import annotations

import json

import pytest

from app.core.types import Status
from app.knowledge.chunking import chunk_service_item
from app.knowledge.index import KnowledgeIndex
from app.orchestrator.history import HistoryTurn
from app.orchestrator.llm import DETERMINISTIC, ModelReply, ModelUnavailableError
from app.orchestrator.pipeline import Pipeline, StreamEnd, StreamStart, TextPiece
from app.orchestrator.resolver import Outcome
from app.orchestrator.router import ConversationState, Intent


class RecordingModel:
    """A model that always answers, and remembers what it was asked.

    Honours the reply contract the briefing asks for. A turn carrying a verdict
    asks for a JSON object declaring it, so that the backend can check the
    words and the verdict still agree; a fake that ignored that would be
    testing a model nobody deploys, and every verdict turn would silently fall
    back to deterministic wording.
    """

    def __init__(self, text: str = "A polished reply.", verdict: str | None = None) -> None:
        self.text = text
        self.verdict = verdict
        self.prompts: list[str] = []
        self.system_instructions: list[str | None] = []

    @property
    def name(self) -> str:
        return "recording-model"

    def _reply_to(self, prompt: str) -> str:
        """What a compliant model would return for this briefing."""
        if "Return one JSON object" not in prompt:
            return self.text
        verdict = self.verdict or _verdict_in(prompt)
        return json.dumps({"verdict": verdict, "reply": self.text})

    def generate(self, prompt: str, *, system_instruction: str | None = None) -> ModelReply:
        self.prompts.append(prompt)
        self.system_instructions.append(system_instruction)
        return ModelReply(self._reply_to(prompt), self.name)

    def stream(self, prompt: str, *, system_instruction: str | None = None):
        self.prompts.append(prompt)
        for word in self.text.split(" "):
            yield f"{word} "


class CountingModel(RecordingModel):
    """A compliant model that also reports what it charged."""

    def __init__(self, *, prompt_tokens: int, output_tokens: int, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._prompt_tokens = prompt_tokens
        self._output_tokens = output_tokens

    def generate(self, prompt: str, *, system_instruction: str | None = None) -> ModelReply:
        self.prompts.append(prompt)
        self.system_instructions.append(system_instruction)
        return ModelReply(
            self._reply_to(prompt),
            self.name,
            prompt_tokens=self._prompt_tokens,
            output_tokens=self._output_tokens,
        )


def _verdict_in(briefing: str) -> str:
    """Read the status code the briefing states, as a compliant model would."""
    for line in briefing.splitlines():
        if line.startswith("Status code:"):
            return line.removeprefix("Status code:").strip()
    return ""


class BrokenModel:
    """A model that is configured but cannot be reached."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "broken-model"

    def generate(self, prompt: str, *, system_instruction: str | None = None) -> ModelReply:
        self.calls += 1
        raise ModelUnavailableError("connection refused")

    def stream(self, prompt: str, *, system_instruction: str | None = None):
        self.calls += 1
        raise ModelUnavailableError("connection refused")
        yield  # pragma: no cover - makes this a generator


class EmptyModel:
    """A model that returns nothing, as safety filters and token limits do."""

    @property
    def name(self) -> str:
        return "empty-model"

    def generate(self, prompt: str, *, system_instruction: str | None = None) -> ModelReply:
        return ModelReply("   ", self.name)

    def stream(self, prompt: str, *, system_instruction: str | None = None):
        yield "   "


class DyingModel:
    """A model that fails partway through, after text is already on the wire."""

    @property
    def name(self) -> str:
        return "dying-model"

    def generate(self, prompt: str, *, system_instruction: str | None = None) -> ModelReply:
        return ModelReply("Complete.", self.name)

    def stream(self, prompt: str, *, system_instruction: str | None = None):
        yield "The verdict is "
        raise ModelUnavailableError("stream reset")


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
        # On-demand items take the quote flow (deterministic). Local items still
        # use the composer and surface the corpus status meaning.
        answer = pipeline.answer("can we order some merch")
        assert answer.status is Status.QUOTE_REQUIRED
        assert "quote" in answer.text.lower()
        assert answer.actions

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
        assert "which one did you mean" in answer.text.lower()
        assert answer.source == DETERMINISTIC

    def test_an_unmatched_request_admits_it(self, pipeline: Pipeline) -> None:
        answer = pipeline.answer("can we hire a hot air balloon for the weekend")
        assert answer.status is None
        text = answer.text.lower()
        assert "couldn't tell" in text or "could not tell" in text or "capability" in text

    def test_ambiguity_is_not_worded_by_the_model(self, corpus, index) -> None:
        """Options are already known; a truncated model list is worse than the
        composed question. The planner may still classify the turn."""
        model = RecordingModel()
        answer = with_model(corpus, index, model).answer(
            "can you translate our web pages into Spanish"
        )
        assert answer.source == DETERMINISTIC
        assert answer.awaiting_answer
        assert not any(prompt.startswith("# Briefing") for prompt in model.prompts)

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
        turn = pipeline.prepare("someone was injured in the branch")
        assert turn.facts.evidence == ()

    def test_declining_mail_is_not_rewritten_from_history(self, corpus, index) -> None:
        """A model shown "No" plus the original request will re-answer the
        request. Mail confirm/cancel is quoted, like handover."""
        model = RecordingModel(
            "Got it! So, about translating those web pages into Spanish — "
            "I'm not seeing a specific service for that."
        )
        pipeline = with_model(corpus, index, model)
        first = pipeline.answer("can we order some merch")
        assert first.next_state.pending_action_kind
        prompted = len(model.prompts)
        history = (
            HistoryTurn("user", "Can you translate our web pages into Spanish?"),
            HistoryTurn("assistant", first.text),
        )
        second = pipeline.answer("No", first.next_state, history=history)
        assert second.source == DETERMINISTIC
        assert "won't send" in second.text.lower() or "no problem" in second.text.lower()
        assert "translat" not in second.text.lower()
        assert len(model.prompts) == prompted


class TestWithAModel:
    # Local / out-of-scope still go through the model. In-scope and on-demand
    # use deterministic business flows (quote tool + CTAs).
    _MODEL_QUESTION = "who handles landlord relationship"

    def test_the_model_writes_the_reply(self, corpus, index) -> None:
        model = RecordingModel("That's a local one — your site team owns it.")
        answer = with_model(corpus, index, model).answer(self._MODEL_QUESTION)
        assert answer.text == "That's a local one — your site team owns it."
        assert answer.source == "recording-model"

    def test_the_model_is_given_the_verdict_not_asked_for_one(self, corpus, index) -> None:
        model = RecordingModel()
        with_model(corpus, index, model).answer(self._MODEL_QUESTION)
        briefing = next(prompt for prompt in model.prompts if prompt.startswith("# Briefing"))
        assert "Verdict" in briefing
        assert self._MODEL_QUESTION in briefing

    def test_the_second_turn_prompt_includes_prior_history(self, corpus, index) -> None:
        model = RecordingModel()
        history = (
            HistoryTurn("user", "Can you translate our web pages into Spanish?"),
            HistoryTurn(
                "assistant",
                "A couple of services could match — which one did you mean?",
            ),
        )
        with_model(corpus, index, model).answer(
            self._MODEL_QUESTION,
            history=history,
        )
        briefing = next(prompt for prompt in model.prompts if prompt.startswith("# Briefing"))
        assert "Recent conversation" in briefing
        assert "Can you translate our web pages into Spanish?" in briefing
        assert self._MODEL_QUESTION in briefing
        assert briefing.index("Verdict") < briefing.index("Recent conversation")

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
        answer = with_model(corpus, index, model).answer(self._MODEL_QUESTION)
        assert model.calls >= 1
        assert answer.degraded
        assert answer.source == DETERMINISTIC
        assert answer.status is Status.LOCAL

    def test_an_empty_completion_is_treated_as_a_failure(self, corpus, index) -> None:
        """Safety filters and token exhaustion both return nothing. Showing a
        blank reply would look like the assistant had no answer."""
        answer = with_model(corpus, index, EmptyModel()).answer(self._MODEL_QUESTION)
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


def collect(pipeline: Pipeline, question: str, state: ConversationState | None = None):
    events = list(pipeline.stream(question, state))
    start = events[0]
    end = events[-1]
    assert isinstance(start, StreamStart)
    assert isinstance(end, StreamEnd)
    pieces = [event.text for event in events if isinstance(event, TextPiece)]
    return start, pieces, end


class TestStreaming:
    def test_the_shape_is_start_then_text_then_end(self, pipeline: Pipeline) -> None:
        start, pieces, end = collect(pipeline, "can we order some merch")
        assert start.resolution.status is Status.QUOTE_REQUIRED
        assert pieces
        assert end.text

    def test_the_verdict_arrives_before_any_prose(self, corpus, index) -> None:
        """The point of streaming here. Scope is a lookup, so the decision is
        known before a single token is generated."""
        events = list(
            with_model(corpus, index, RecordingModel()).stream("can we order some merch")
        )
        first = events[0]
        assert isinstance(first, StreamStart)
        assert first.resolution.status is Status.QUOTE_REQUIRED
        assert not any(isinstance(event, TextPiece) for event in events[:1])

    def test_the_streamed_text_matches_the_end_event(self, corpus, index) -> None:
        _, pieces, end = collect(
            with_model(corpus, index, RecordingModel("One two three.")), "merch"
        )
        assert "".join(pieces).strip() == end.text

    def test_streaming_and_non_streaming_agree_on_the_verdict(self, pipeline: Pipeline) -> None:
        for question in (
            "can we order some merch",
            "can you translate our web pages into Spanish",
            "can we hire a hot air balloon",
        ):
            start, _, _ = collect(pipeline, question)
            assert start.resolution.status == pipeline.answer(question).status

    def test_a_model_that_fails_before_emitting_falls_back_invisibly(
        self, corpus, index
    ) -> None:
        """Nothing has reached the user yet, so the deterministic answer can
        still be substituted whole."""
        question = "who handles landlord relationship"
        _, pieces, end = collect(with_model(corpus, index, BrokenModel()), question)
        assert end.degraded
        assert not end.truncated
        assert end.source == DETERMINISTIC
        assert pieces

    def test_a_model_that_dies_midway_on_an_unguarded_turn_reports_truncation(
        self, corpus, index
    ) -> None:
        """Bytes already sent cannot be retracted. Appending a second, different
        answer would be worse than admitting the first one stopped.

        Turns that carry a verdict or a figure are buffered and checked before
        anything is shown, so a mid-stream death there is invisible. This uses
        a capabilities question, which is safe to stream.
        """
        question = "what can you help me with"
        _, pieces, end = collect(with_model(corpus, index, DyingModel()), question)
        assert end.truncated
        assert end.text == "".join(pieces)

    def test_an_empty_stream_falls_back(self, corpus, index) -> None:
        question = "who handles landlord relationship"
        _, pieces, end = collect(with_model(corpus, index, EmptyModel()), question)
        assert end.degraded
        assert end.text.strip()
        assert "".join(pieces).strip()

    def test_a_handover_streams_the_fixed_wording_and_skips_the_model(
        self, corpus, index
    ) -> None:
        model = RecordingModel()
        start, pieces, end = collect(
            with_model(corpus, index, model), "someone was injured in the branch"
        )
        assert model.prompts == []
        assert start.route.needs_a_human
        assert end.source == DETERMINISTIC
        assert "safety" in "".join(pieces).lower()

    def test_the_stream_carries_state_forward(self, pipeline: Pipeline) -> None:
        start, _, _ = collect(pipeline, "can you translate our web pages into Spanish")
        assert start.awaiting_answer
        assert start.next_state.pending_candidates

        follow_up, _, _ = collect(pipeline, "the second one", start.next_state)
        assert follow_up.resolution.status is not None


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


class TestTheModelDeclaresTheVerdictItStates:
    """The check that replaced a phrasebook.

    ``guard.py`` reads a reply for wordings that sound like a verdict, and can
    only recognise the ones somebody thought of in advance. A model that
    paraphrases eventually finds one nobody did: "Building a new website from
    scratch isn't something the central marketing team handles" turned an
    in-scope verdict into a refusal and passed, because that phrasing is not in
    the list. Asking the model which verdict it just conveyed catches the flip
    however it is worded.
    """

    _QUESTION = "who handles landlord relationship"

    def test_a_compliant_reply_is_used(self, corpus, index) -> None:
        model = RecordingModel("That's a local one — your site team owns it.")
        answer = with_model(corpus, index, model).answer(self._QUESTION)
        assert answer.text == "That's a local one — your site team owns it."
        assert answer.source == "recording-model"
        assert not answer.degraded

    def test_a_flipped_verdict_is_discarded_however_it_is_phrased(
        self, corpus, index
    ) -> None:
        """The reply reads plausibly and trips no regex. It still must not ship."""
        model = RecordingModel(
            "That isn't something the central marketing team handles.",
            verdict="out_of_scope",
        )
        answer = with_model(corpus, index, model).answer(self._QUESTION)
        assert answer.source == DETERMINISTIC
        assert answer.degraded
        assert "central marketing team handles" not in answer.text

    def test_the_briefing_states_the_token_to_declare(self, corpus, index) -> None:
        """The model is told which word to copy rather than left to translate
        "Local — Taken by local or operation teams" into an internal name it
        has never been shown."""
        model = RecordingModel()
        with_model(corpus, index, model).answer(self._QUESTION)
        briefing = next(p for p in model.prompts if p.startswith("# Briefing"))
        assert f"Status code: {Status.LOCAL.value}" in briefing

    def test_a_reply_that_ignores_the_format_falls_back_quietly(
        self, corpus, index
    ) -> None:
        """Not an offence, just unusable. Losing a turn's phrasing costs far
        less than shipping prose nobody checked."""

        class PlainProseModel(RecordingModel):
            def _reply_to(self, prompt: str) -> str:
                return self.text

        model = PlainProseModel("Local team owns it.")
        answer = with_model(corpus, index, model).answer(self._QUESTION)
        assert answer.source == DETERMINISTIC
        assert answer.degraded

    def test_a_turn_with_no_verdict_is_not_asked_for_one(self, corpus, index) -> None:
        """The contract applies only where there is a verdict to contradict."""
        model = RecordingModel()
        with_model(corpus, index, model).answer("hello")
        assert all("Return one JSON object" not in p for p in model.prompts)


class TestTurnCost:
    """A turn calls the model twice. The useful question is always what the
    *question* cost, so the two are summed before anyone sees them."""

    def test_a_turn_sums_planning_and_wording(self, corpus, index) -> None:
        """Two calls at 125 each. The planner's answer is discarded here - a
        wording model does not emit a valid plan - and it is billed anyway,
        which is the point: the cost is incurred whatever is done with it."""
        model = CountingModel(prompt_tokens=100, output_tokens=25)
        answer = with_model(corpus, index, model).answer("who handles landlord relationship")
        assert answer.plan is not None
        assert answer.plan.tokens == 125
        assert answer.tokens == 250

    def test_the_deterministic_path_costs_nothing(self, pipeline: Pipeline) -> None:
        assert pipeline.answer("who handles landlord relationship").tokens == 0

    def test_a_rejected_reply_is_still_billed(self, corpus, index) -> None:
        """The expensive failures are the ones a guard throws away. Charging
        them to nobody would hide a misbehaving model behind a flat cost."""
        model = CountingModel(prompt_tokens=100, output_tokens=25, verdict="out_of_scope")
        answer = with_model(corpus, index, model).answer("who handles landlord relationship")
        assert answer.source == DETERMINISTIC
        assert answer.degraded
        # Planner call plus the rejected wording call: both were paid for.
        assert answer.tokens == 250
