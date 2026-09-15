"""One message, two services, one lookup.

"I need the QR reports and access to the international goals dashboard" was
answered with the QR reports' verdict, correctly, and then "Good news on the
international goals dashboard though! That's something the central marketing
team can definitely help with." Nothing looked that up. These assert that the
second service gets no verdict from anyone — model or fallback — and that the
person is asked to send it on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from app.core.types import Status
from app.knowledge.chunking import chunk_service_item
from app.knowledge.index import KnowledgeIndex
from app.orchestrator.guard import inspect
from app.orchestrator.pipeline import Pipeline
from app.orchestrator.planner import RulePlanner, _other_services

MESSAGE = "I need the QR reports and access to the international goals dashboard"
LOOKED_UP = "QR reports"
OTHER = "international goals dashboard"


@dataclass(frozen=True, slots=True)
class TwoServicePlanner:
    """The rule plan, with the split a model planner makes for this message."""

    inner: RulePlanner

    def plan(self, message, route, state):  # type: ignore[no-untyped-def]
        plan = self.inner.plan(message, route, state)
        if message != MESSAGE:
            return plan
        return plan.with_slots(service_phrase=LOOKED_UP, other_services=(OTHER,))


@pytest.fixture(scope="module")
def pipeline(corpus):
    chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
    built = Pipeline(corpus.catalog, KnowledgeIndex.build(chunks), model=None)
    built.planner = TwoServicePlanner(RulePlanner(corpus.catalog))
    return built


class TestThePlannerOnlyKeepsWordsTheUserTyped:
    def test_a_phrase_from_the_message_is_kept(self) -> None:
        assert _other_services([OTHER], MESSAGE, LOOKED_UP) == (OTHER,)

    def test_an_invented_phrase_is_dropped(self) -> None:
        """Only ever used to say something was *not* checked, but a service the
        person never mentioned would still be a confusing thing to be told."""
        assert _other_services(["social media calendar"], MESSAGE, LOOKED_UP) == ()

    def test_the_looked_up_service_is_not_listed_again(self) -> None:
        assert _other_services(["qr   Reports"], MESSAGE, LOOKED_UP) == ()

    def test_malformed_output_is_ignored(self) -> None:
        assert _other_services("goals dashboard", MESSAGE, LOOKED_UP) == ()
        assert _other_services([None, 3, ""], MESSAGE, LOOKED_UP) == ()


class TestTheBriefing:
    def test_the_other_service_is_named_as_not_looked_up(self, pipeline) -> None:
        text = pipeline.prepare(MESSAGE).briefing()
        assert "## Also asked about, and not looked up" in text
        assert f"- {OTHER}" in text
        assert "Give no verdict for these" in text

    def test_a_single_service_message_has_no_such_block(self, pipeline) -> None:
        assert "not looked up" not in pipeline.prepare("can we order some merch").briefing()


class TestTheGuard:
    @pytest.fixture
    def facts(self, pipeline):
        facts = pipeline.prepare(MESSAGE).facts
        assert facts.scope is not None
        assert facts.scope.status is Status.OUT_OF_SCOPE, "the premise of the case"
        return facts

    def test_the_reply_that_was_shipped_is_refused(self, facts) -> None:
        reply = (
            "QR code reports aren't something central marketing covers, but we might "
            "still be able to help. Good news on the international goals dashboard "
            "though! That's something the central marketing team can definitely help with."
        )
        violation = inspect(reply, facts)
        assert violation is not None
        assert violation.kind == "verdict"
        assert OTHER in violation.detail

    @pytest.mark.parametrize(
        "claim",
        [
            "The international goals dashboard is free of charge.",
            "The international goals dashboard will need a quote.",
            "The goals dashboard is handled locally.",
            "As for the international dashboard, that's covered.",
        ],
    )
    def test_any_verdict_word_for_it_is_refused(self, facts, claim) -> None:
        assert inspect(f"QR code reports are out of scope. {claim}", facts) is not None

    def test_deferring_it_is_allowed(self, facts) -> None:
        reply = (
            "QR code reports aren't something central marketing covers, but your "
            "Account Manager might still be able to help. I haven't checked the "
            "international goals dashboard yet, so send that as its own question."
        )
        assert inspect(reply, facts) is None

    def test_the_looked_up_verdict_after_naming_it_is_allowed(self, facts) -> None:
        """Naming the other service and then giving the looked-up verdict in the
        next sentence is the right answer, not a leak."""
        reply = (
            "I'll check the international goals dashboard separately. "
            "QR code reports are out of scope, but we might still be able to help."
        )
        assert inspect(reply, facts) is None

    def test_without_another_service_nothing_changes(self, pipeline) -> None:
        facts = pipeline.prepare(MESSAGE).facts
        plain = replace(facts, plan=facts.plan.with_slots(other_services=()))
        reply = "QR code reports are out of scope. Good news, we can definitely help with posters."
        assert inspect(reply, plain) is None


class TestTheReplyWithoutAModel:
    def test_it_defers_the_other_service(self, pipeline) -> None:
        answer = pipeline.answer(MESSAGE)
        assert f"**{OTHER}**" in answer.text
        assert "its own question" in answer.text

    def test_it_still_gives_the_looked_up_verdict(self, pipeline) -> None:
        answer = pipeline.answer(MESSAGE)
        assert answer.resolution.status is Status.OUT_OF_SCOPE

    def test_its_own_fallback_passes_the_guard(self, pipeline) -> None:
        turn = pipeline.prepare(MESSAGE)
        assert inspect(turn.facts.fallback_text, turn.facts) is None
