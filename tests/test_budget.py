"""Budget store and tool — numbers come from the ledger, never the model."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.knowledge.chunking import chunk_service_item
from app.knowledge.index import KnowledgeIndex
from app.orchestrator.llm import DETERMINISTIC
from app.orchestrator.pipeline import Pipeline
from app.orchestrator.router import Intent
from app.store.budget import XlsxBudgetStore, build_budget_store, canonical_month
from app.tools.budget import answer_budget
from tests.test_pipeline import RecordingModel

FIXTURE = Path("fixtures/budget/acme_scope_db.xlsx")


@pytest.fixture(scope="module")
def store() -> XlsxBudgetStore:
    assert FIXTURE.is_file(), "budget fixture missing — copy the workbook into fixtures/budget/"
    return XlsxBudgetStore(FIXTURE)


class TestWorkbookStore:
    def test_branches_load(self, store: XlsxBudgetStore) -> None:
        names = {branch.name for branch in store.branches()}
        assert "Acme Milton Keynes" in names
        assert "Acme Manchester" in names
        assert "United Kingdom" not in names  # rollup, not a branch

    def test_resolve_short_and_branded_names(self, store: XlsxBudgetStore) -> None:
        assert store.resolve_branch("Milton Keynes").name == "Acme Milton Keynes"
        assert store.resolve_branch("Acme Manchester").name == "Acme Manchester"

    def test_fiscal_month_uses_calendar_starts(self, store: XlsxBudgetStore) -> None:
        # Fiscal Aug starts 2026-07-27.
        assert store.fiscal_month_for(date(2026, 7, 26)) == "Jul"
        assert store.fiscal_month_for(date(2026, 7, 27)) == "Aug"
        assert store.fiscal_month_for(date(2026, 8, 10)) == "Aug"

    def test_milton_keynes_august_spent(self, store: XlsxBudgetStore) -> None:
        branch = store.resolve_branch("Milton Keynes")
        assert branch is not None
        snap = store.snapshot(branch, "Aug")
        assert snap.cap == 500
        assert snap.spent == pytest.approx(51.68)
        assert snap.remaining == pytest.approx(448.32)
        assert snap.lines


class TestBudgetTool:
    def test_asks_when_branch_missing(self, store: XlsxBudgetStore) -> None:
        result = answer_budget("how much budget is left", store)
        assert result.ask_branch
        assert "Which branch" in result.text

    def test_uses_session_branch(self, store: XlsxBudgetStore) -> None:
        result = answer_budget(
            "how much budget is left",
            store,
            session_branch="Acme Oakville",
            today=date(2026, 3, 15),
        )
        assert not result.ask_branch
        assert result.snapshot is not None
        assert result.snapshot.branch.name == "Acme Oakville"
        assert "Oakville" in result.text

    def test_month_in_message(self, store: XlsxBudgetStore) -> None:
        result = answer_budget(
            "budget left at Milton Keynes in August",
            store,
            today=date(2026, 1, 1),
        )
        assert result.snapshot is not None
        assert result.snapshot.month == "Aug"

    def test_uk_country_rollup(self, store: XlsxBudgetStore) -> None:
        result = answer_budget(
            "how much do we have for all of the UK branches?",
            store,
            today=date(2026, 8, 10),
        )
        assert not result.ask_branch
        assert len(result.snapshots) >= 4
        assert all(
            snap.branch.country == "United Kingdom" for snap in result.snapshots
        )
        assert "United Kingdom" in result.text
        assert "London" in result.text
        assert "Remaining:" in result.text

    def test_france_maps_to_paris_site(self, store: XlsxBudgetStore) -> None:
        result = answer_budget(
            "how much budget do we have for france?",
            store,
            today=date(2026, 8, 10),
        )
        assert not result.ask_branch
        assert result.resolved_country == "Paris"
        assert any("Paris" in snap.branch.name for snap in result.snapshots)

    def test_all_of_them_lists_every_branch(self, store: XlsxBudgetStore) -> None:
        result = answer_budget("all of them", store, today=date(2026, 8, 10))
        assert not result.ask_branch
        assert len(result.snapshots) == len(store.branches())
        assert "All branches" in result.text

    def test_all_of_them_with_sticky_country_stays_in_country(
        self, store: XlsxBudgetStore
    ) -> None:
        result = answer_budget(
            "all of them",
            store,
            sticky_country="Canada",
            today=date(2026, 8, 10),
        )
        assert result.resolved_country == "Canada"
        assert all(snap.branch.country == "Canada" for snap in result.snapshots)

    def test_sticky_slots_fill_bare_followup(self, store: XlsxBudgetStore) -> None:
        result = answer_budget(
            "and for the uk?",
            store,
            sticky_country="Canada",
            today=date(2026, 8, 10),
        )
        assert result.resolved_country == "United Kingdom"
        assert result.scope_source == "message"

    def test_unavailable_store(self) -> None:
        result = answer_budget("budget at London", None)
        assert "aren't available" in result.text


class TestPipelineBudget:
    def test_budget_never_reaches_the_model(self, corpus, store: XlsxBudgetStore) -> None:
        model = RecordingModel("I invented a budget figure of 99999.")
        chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
        pipeline = Pipeline(
            corpus.catalog,
            KnowledgeIndex.build(chunks),
            model=model,
            budget_store=store,
            branches=tuple(branch.name for branch in store.branches()),
        )

        from app.tools.flows import SessionIdentity

        answer = pipeline.answer(
            "how much budget is left at Milton Keynes in August",
            identity=SessionIdentity(),
        )
        assert model.prompts == []
        assert answer.source == DETERMINISTIC
        assert answer.route.intent is Intent.BUDGET
        assert "99999" not in answer.text
        assert "Milton Keynes" in answer.text
        assert "448" in answer.text or "448.32" in answer.text

    def test_sticky_canada_then_uk_never_reaches_model(
        self, corpus, store: XlsxBudgetStore
    ) -> None:
        model = RecordingModel("I can only give budget details for Canada.")
        chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
        pipeline = Pipeline(
            corpus.catalog,
            KnowledgeIndex.build(chunks),
            model=model,
            budget_store=store,
            branches=tuple(branch.name for branch in store.branches()),
        )
        from app.tools.flows import SessionIdentity

        first = pipeline.answer(
            "what are the budget for canada?",
            identity=SessionIdentity(),
        )
        assert first.next_state.active_tool == "budget"
        assert first.next_state.budget_country == "Canada"
        assert "Canada" in first.text

        second = pipeline.answer(
            "and for the uk?",
            state=first.next_state,
            identity=SessionIdentity(),
        )
        assert model.prompts == []
        assert second.source == DETERMINISTIC
        assert second.route.intent is Intent.BUDGET
        assert second.route.matched == "sticky:budget"
        assert "United Kingdom" in second.text
        assert "Canada" not in second.text or "United Kingdom" in second.text
        assert "I can only" not in second.text
        assert second.next_state.budget_country == "United Kingdom"

    def test_sticky_all_of_them_and_bare_london(
        self, corpus, store: XlsxBudgetStore
    ) -> None:
        chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
        pipeline = Pipeline(
            corpus.catalog,
            KnowledgeIndex.build(chunks),
            budget_store=store,
            branches=tuple(branch.name for branch in store.branches()),
        )
        from app.tools.flows import SessionIdentity

        ask = pipeline.answer("how much budget is left", identity=SessionIdentity())
        assert ask.next_state.active_tool == "budget"
        all_sites = pipeline.answer(
            "all of them",
            state=ask.next_state,
            identity=SessionIdentity(),
        )
        assert "All branches" in all_sites.text
        assert len(all_sites.next_state.budget_country or "") == 0 or (
            all_sites.next_state.budget_country is None
        )

        canada = pipeline.answer(
            "what are the budget for canada?",
            identity=SessionIdentity(),
        )
        london = pipeline.answer(
            "London",
            state=canada.next_state,
            identity=SessionIdentity(),
        )
        assert london.route.intent is Intent.BUDGET
        assert "Acme London" in london.text or "London" in london.text
        assert london.next_state.budget_branch == "Acme London"

    def test_sticky_budget_exits_to_scoping(self, corpus, store: XlsxBudgetStore) -> None:
        chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
        pipeline = Pipeline(
            corpus.catalog,
            KnowledgeIndex.build(chunks),
            budget_store=store,
            branches=tuple(branch.name for branch in store.branches()),
        )
        from app.tools.flows import SessionIdentity

        first = pipeline.answer(
            "what are the budget for canada?",
            identity=SessionIdentity(),
        )
        second = pipeline.answer(
            "can we do billboards?",
            state=first.next_state,
            identity=SessionIdentity(),
        )
        assert second.route.intent is Intent.SCOPING
        assert second.next_state.active_tool is None

    def test_build_budget_store_from_default_path(self) -> None:
        loaded = build_budget_store(xlsx_path=FIXTURE)
        assert loaded is not None
        assert loaded.resolve_branch("London") is not None


def test_canonical_month_helpers() -> None:
    assert canonical_month("august") == "Aug"
    assert canonical_month("AUG") == "Aug"
