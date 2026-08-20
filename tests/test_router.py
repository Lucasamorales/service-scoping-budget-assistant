"""Invariants of the intent router.

The safety property: a message about an injury, a legal threat or a data
protection request must reach a person, whatever else it happens to mention.
Everything else in here is about not inventing context the user cannot see.

Corpus-shaped expectations live in ``evals/routing.json``.
"""

from __future__ import annotations

import pytest

from app.orchestrator.router import (
    HANDOVER_TOPICS,
    ConversationState,
    Intent,
    Router,
)


@pytest.fixture(scope="module")
def router() -> Router:
    return Router()


class TestHandoverWins:
    @pytest.mark.parametrize(
        "message",
        [
            "someone was injured in the branch",
            "a customer is threatening legal action",
            "they want their personal data deleted",
            "a journalist has been in touch",
            "should we refund this booking",
            "can we get a discount on this",
        ],
    )
    def test_sensitive_subjects_reach_a_person(self, router: Router, message: str) -> None:
        assert router.route(message).intent is Intent.HANDOVER

    def test_hr_requests_are_not_a_special_handover(self, router: Router) -> None:
        """Employment asks are outside capability — not an HR handover banner."""
        for message in (
            "there is a grievance against a staff member",
            "fire jeremy",
            "we need to fire someone",
        ):
            assert router.route(message).intent is not Intent.HANDOVER

    def test_a_service_mentioned_alongside_an_injury_does_not_win(self, router: Router) -> None:
        """The case the ordering exists for. Photography is a real catalog
        section, and a plausible scoping answer here would be grotesque."""
        route = router.route("we were shooting photos when someone got hurt, can we use them")
        assert route.intent is Intent.HANDOVER
        assert route.handover_topic is not None
        assert route.handover_topic.name == "safety"

    def test_handover_outranks_a_pending_question(self, router: Router) -> None:
        state = ConversationState(pending_candidates=("photography--billboards",))
        route = router.route("forget that, someone has been injured", state)
        assert route.intent is Intent.HANDOVER

    def test_handover_outranks_a_budget_question(self, router: Router) -> None:
        route = router.route("how much budget is left after the refund we owe them")
        assert route.intent is Intent.HANDOVER

    def test_every_handover_explains_itself_to_the_user(self, router: Router) -> None:
        """The reason is shown to the person who asked, so it has to read like
        an answer rather than a rule firing."""
        for _, topic in HANDOVER_TOPICS:
            assert topic.reason.endswith(".")
            assert len(topic.reason) > 40

    def test_handover_is_flagged_for_callers(self, router: Router) -> None:
        assert router.route("someone was injured").needs_a_human
        assert not router.route("can we do billboards").needs_a_human


class TestOrdinaryIntents:
    @pytest.mark.parametrize(
        "message",
        [
            "how much budget is left",
            "how much money do we have in the london branch",
            "what's left in the London branch",
            "funds remaining at Milton Keynes",
        ],
    )
    def test_money_and_remaining_questions_are_budget(
        self, router: Router, message: str
    ) -> None:
        assert router.route(message).intent is Intent.BUDGET

    def test_sticky_budget_keeps_followups_on_budget(self, router: Router) -> None:
        state = ConversationState(active_tool="budget", budget_country="Canada")
        assert router.route("all of them", state).intent is Intent.BUDGET
        assert router.route("and for the uk?", state).intent is Intent.BUDGET
        assert router.route("what about the UK?", state).intent is Intent.BUDGET
        assert router.route("August", state).intent is Intent.BUDGET

    def test_sticky_budget_exits_on_scoping(self, router: Router) -> None:
        state = ConversationState(active_tool="budget", budget_country="Canada")
        assert router.route("can we do billboards?", state).intent is Intent.SCOPING

    def test_sticky_budget_bare_branch_stays_on_budget(self) -> None:
        router = Router(branches=("Acme London", "Acme Manchester"))
        state = ConversationState(active_tool="budget", budget_country="Canada")
        route = router.route("London", state)
        assert route.intent is Intent.BUDGET
        assert route.branch == "Acme London"

    def test_a_bare_service_name_is_a_scoping_question(self, router: Router) -> None:
        assert router.route("billboards?").intent is Intent.SCOPING

    def test_a_negative_review_is_business_as_usual(self, router: Router) -> None:
        """Review management is a catalog item handled locally. The handover
        patterns must not swallow it, or a routine question gets escalated."""
        assert router.route("we got a bad review, who deals with those").intent is Intent.SCOPING

    def test_an_empty_message_is_unknown(self, router: Router) -> None:
        assert router.route("").intent is Intent.UNKNOWN
        assert router.route("   ").intent is Intent.UNKNOWN

    def test_punctuation_only_is_unknown(self, router: Router) -> None:
        assert router.route("???").intent is Intent.UNKNOWN

    def test_every_route_records_its_trigger(self, router: Router) -> None:
        for message in ("how much budget is left", "someone was injured", "morning"):
            assert router.route(message).matched

    def test_every_route_explains_itself(self, router: Router) -> None:
        for message in ("billboards?", "someone was injured", "", "hi"):
            assert router.route(message).explain()


class TestFollowUps:
    def test_a_bare_continuation_carries_the_previous_subject(self, router: Router) -> None:
        state = ConversationState(last_item_ids=("photography--billboards",))
        route = router.route("and for Basingstoke?", state)
        assert route.intent is Intent.FOLLOW_UP
        assert route.carried_item_ids == ("photography--billboards",)

    def test_nothing_is_carried_when_there_is_no_history(self, router: Router) -> None:
        """Inventing a subject is worse than treating it as a fresh question,
        because the user cannot see what was assumed."""
        route = router.route("and for Basingstoke?")
        assert route.intent is not Intent.FOLLOW_UP
        assert route.carried_item_ids == ()

    def test_a_complete_question_is_not_a_follow_up(self, router: Router) -> None:
        state = ConversationState(last_item_ids=("photography--billboards",))
        message = (
            "and while I remember we need a full set of interior photographs "
            "for the website refresh next month"
        )
        route = router.route(message, state)
        assert route.intent is Intent.SCOPING
        assert route.carried_item_ids == ()

    def test_a_follow_up_inherits_the_previous_branch(self, router: Router) -> None:
        state = ConversationState(last_item_ids=("photography--billboards",), last_branch="Bedford")
        assert router.route("what about posters", state).branch == "Bedford"


class TestClarificationReplies:
    CANDIDATES = ("photography--billboards", "photography--hoarding")

    @pytest.fixture
    def waiting(self) -> ConversationState:
        return ConversationState(pending_candidates=self.CANDIDATES)

    def test_an_ordinal_selects(self, router: Router, waiting: ConversationState) -> None:
        route = router.route("the second one", waiting)
        assert route.intent is Intent.CLARIFICATION_REPLY
        assert route.selected_item_id == "photography--hoarding"

    def test_a_digit_selects(self, router: Router, waiting: ConversationState) -> None:
        assert router.route("1", waiting).selected_item_id == "photography--billboards"

    def test_a_name_selects(self, router: Router, waiting: ConversationState) -> None:
        """'one' here is filler, not a number. Reading it as an ordinal picked
        the wrong option, so names are matched before counting."""
        assert router.route("the hoarding one", waiting).selected_item_id == (
            "photography--hoarding"
        )

    def test_an_out_of_range_number_selects_nothing(
        self, router: Router, waiting: ConversationState
    ) -> None:
        assert router.route("9", waiting).intent is not Intent.CLARIFICATION_REPLY

    def test_changing_the_subject_abandons_the_question(
        self, router: Router, waiting: ConversationState
    ) -> None:
        """People walk away from questions. Answering the abandoned one is
        worse than dropping it."""
        assert router.route("actually how much budget is left", waiting).intent is Intent.BUDGET

    def test_an_ambiguous_reply_selects_nothing(
        self, router: Router, waiting: ConversationState
    ) -> None:
        """Both candidates are Photography, so naming the section chooses
        neither. Guessing here silently answers the wrong question."""
        route = router.route("the photography one", waiting)
        assert route.selected_item_id is None

    def test_selection_only_applies_while_a_question_is_open(self, router: Router) -> None:
        assert router.route("the second one").intent is not Intent.CLARIFICATION_REPLY


class TestBranches:
    def test_no_branch_is_reported_without_a_glossary(self, router: Router) -> None:
        """The glossary has not arrived. Reporting nothing is honest; the
        assistant should ask rather than assume which site is meant."""
        assert router.route("can we do billboards at Bedford").branch is None

    def test_a_known_branch_is_recognised(self) -> None:
        router = Router(branches=("Bedford", "Basingstoke", "Manchester"))
        assert router.route("can we do billboards at Bedford").branch == "Bedford"

    def test_branch_matching_ignores_case(self) -> None:
        router = Router(branches=("Bedford",))
        assert router.route("what about BEDFORD").branch == "Bedford"

    def test_a_branch_name_inside_another_word_does_not_match(self) -> None:
        router = Router(branches=("Bed",))
        assert router.route("we need this embedded on the website").branch is None
