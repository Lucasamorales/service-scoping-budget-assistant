"""What the output guard refuses to let through.

The model is asked for wording, not judgement. These assert the refusal, since
"we told it not to" is not a control. Each case is a reply that would read as
perfectly authoritative to the person receiving it.
"""

from __future__ import annotations

from app.orchestrator.facts import FactPack
from app.orchestrator.guard import inspect
from app.orchestrator.plan import Capability, Plan
from app.store.budget import BudgetSnapshot, BranchRef
from app.tools.budget import BudgetToolResult

MILTON_KEYNES = BranchRef(
    key="acme-milton-keynes",
    name="Acme Milton Keynes",
    country="United Kingdom",
    location="Milton Keynes",
)


def budget_facts(*, remaining: float | None = 448.32, cap: float | None = 500.0) -> FactPack:
    snapshot = BudgetSnapshot(
        branch=MILTON_KEYNES,
        month="Aug",
        cap=cap,
        spent=51.68,
        remaining=remaining,
        lines=(),
    )
    # The deterministic sentence has to match the snapshot: every figure in it is
    # permitted, so a helper that always mentioned a balance would hand the guard
    # the very number the unknown-cap case is supposed to reject.
    fallback = (
        f"Acme Milton Keynes has {remaining} left in Aug."
        if remaining is not None
        else "Acme Milton Keynes has no cap recorded for Aug. Spent 51.68."
    )
    return FactPack(
        plan=Plan((Capability.BUDGET,)),
        satisfied=(Capability.BUDGET,),
        budget=BudgetToolResult(
            text="Acme Milton Keynes — Aug",
            snapshot=snapshot,
            snapshots=(snapshot,),
            resolved_country="United Kingdom",
            resolved_branch="Acme Milton Keynes",
            resolved_month="Aug",
        ),
        fallback_text=fallback,
    )


class TestFigures:
    def test_an_invented_figure_is_refused(self) -> None:
        violation = inspect("You have 99999 left.", budget_facts())
        assert violation is not None
        assert violation.kind == "figure"

    def test_a_figure_from_the_facts_is_allowed(self) -> None:
        assert inspect("You have 448.32 left at Milton Keynes.", budget_facts()) is None

    def test_small_counts_are_not_treated_as_money(self) -> None:
        """"3 of those sit with your local team" is a fact about a list."""
        assert inspect("There are 3 lines logged this month.", budget_facts()) is None


class TestWrongCountry:
    def test_a_reply_about_another_country_is_refused(self) -> None:
        """The sticky-thread failure: no invented figure, still the wrong answer.

        A model that keeps its previous framing after "and for the uk?" answers
        about Canada, and nothing in the numbers gives it away.
        """
        violation = inspect("I can only give budget details for Canada.", budget_facts())
        assert violation is not None
        assert violation.kind == "place"
        assert "canada" in violation.detail

    def test_the_country_that_was_looked_up_is_allowed(self) -> None:
        assert inspect("In the United Kingdom you have 448.32 left.", budget_facts()) is None

    def test_an_alias_of_the_looked_up_country_is_allowed(self) -> None:
        assert inspect("The UK site has 448.32 remaining.", budget_facts()) is None

    def test_a_country_is_only_checked_when_a_budget_was_looked_up(self) -> None:
        """Scope answers mention countries innocently; there is nothing to
        contradict when no budget lookup happened."""
        facts = FactPack(plan=Plan((Capability.SCOPE,)), fallback_text="Merch needs a quote.")
        assert inspect("Your Canada team can help with merch.", facts) is None


class TestUnknownCap:
    def test_an_unknown_remaining_budget_permits_no_balance(self) -> None:
        """With no cap on the sheet there is no balance, so any figure offered as
        one is invented."""
        facts = budget_facts(cap=None, remaining=None)
        violation = inspect("You have 448.32 left.", facts)
        assert violation is not None
        assert violation.kind == "figure"

    def test_spend_is_still_sayable_when_the_cap_is_unknown(self) -> None:
        facts = budget_facts(cap=None, remaining=None)
        assert inspect("51.68 has been logged so far.", facts) is None


class TestMailClaims:
    def test_claiming_an_email_was_sent_when_none_was_is_refused(self) -> None:
        violation = inspect("I've sent that to your Account Manager.", budget_facts())
        assert violation is not None
        assert violation.kind == "mail"


def test_an_empty_reply_is_refused() -> None:
    violation = inspect("   ", budget_facts())
    assert violation is not None
    assert violation.kind == "empty"
