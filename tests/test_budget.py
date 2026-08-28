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


class TestMissingCapIsUnknown:
    """A cap the sheet does not have is unknown, not zero.

    Defaulting to 0.0 turned a parsing gap into "there is nothing left", which
    reads as a real budget decision and stops a legitimate request.
    """

    def test_a_month_with_no_cap_has_no_remaining(self) -> None:
        """Built directly, because the shipped fixture caps every month — which
        is exactly why this case went unnoticed."""
        from app.core.keys import branch_key
        from app.store.budget import BranchRef, _snapshot, _WorkbookData

        branch = BranchRef(
            key=branch_key("Acme Nowhere"),
            name="Acme Nowhere",
            country="United Kingdom",
            location="Nowhere",
        )
        data = _WorkbookData(
            branches=(branch,),
            by_key={branch.key: branch},
            caps={branch.key: {"Jul": 500.0}},  # no August row
            fiscal=(),
            spend=(),
        )
        snap = _snapshot(data, branch, "Aug", lambda when: "Aug")
        assert snap.cap is None
        assert snap.remaining is None
        assert not snap.cap_known

    def test_spend_without_a_cap_does_not_become_a_negative_balance(self) -> None:
        """The old default made remaining equal minus the spend."""
        from datetime import date as _date

        from app.core.keys import branch_key
        from app.store.budget import SpendLine, BranchRef, _snapshot, _WorkbookData

        branch = BranchRef(
            key=branch_key("Acme Nowhere"),
            name="Acme Nowhere",
            country="United Kingdom",
            location="Nowhere",
        )
        line = SpendLine(
            branch="Acme Nowhere",
            country="United Kingdom",
            media_type="Print",
            description="posters",
            po_number="PO1",
            requester="Alex",
            po_date=_date(2026, 8, 1),
            amount=120.0,
            month_label="Aug",
        )
        data = _WorkbookData(
            branches=(branch,),
            by_key={branch.key: branch},
            caps={},
            fiscal=(),
            spend=(line,),
        )
        snap = _snapshot(data, branch, "Aug", lambda when: "Aug")
        assert snap.spent == pytest.approx(120.0)
        assert snap.remaining is None

    def test_a_known_cap_still_reports_a_balance(self, store: XlsxBudgetStore) -> None:
        branch = store.resolve_branch("Milton Keynes")
        assert branch is not None
        snap = store.snapshot(branch, "Aug")
        assert snap.cap_known
        assert snap.remaining == pytest.approx(448.32)

    def test_an_unknown_cap_is_said_rather_than_shown_as_zero(self) -> None:
        from app.store.budget import BudgetSnapshot, BranchRef
        from app.tools.budget import _format_snapshot

        snap = BudgetSnapshot(
            branch=BranchRef(key="k", name="Acme Nowhere", country="UK", location="Nowhere"),
            month="Aug",
            cap=None,
            spent=120.0,
            remaining=None,
            lines=(),
        )
        text = _format_snapshot(snap)
        assert "unknown" in text
        assert "can't say what is left" in text
        # The one thing it must never do is imply an empty budget.
        assert "Remaining: 0" not in text


class TestCacheTtl:
    """Budget figures are re-read, not frozen at container start."""

    def test_a_zero_ttl_never_reloads(self) -> None:
        from types import SimpleNamespace

        from app.store.budget import _CachedWorkbook

        calls = []

        def loader():
            calls.append(1)
            return SimpleNamespace(branches=())

        cache = _CachedWorkbook(loader, ttl_seconds=0)
        for _ in range(3):
            assert cache.data is not None
        assert len(calls) == 1

    def test_an_expired_cache_reloads(self) -> None:
        from types import SimpleNamespace

        from app.store import budget as budget_module

        calls = []

        def loader():
            calls.append(len(calls))
            return SimpleNamespace(branches=(), label=f"load-{len(calls)}")

        cache = budget_module._CachedWorkbook(loader, ttl_seconds=1)
        assert cache.data.label == "load-1"
        # Reach back in time rather than sleeping.
        cache._tried_at -= 5
        assert cache.data.label == "load-2"
        assert len(calls) == 2

    def test_a_failed_refresh_keeps_serving_the_last_good_data(self) -> None:
        """Going dark on a transient Sheets error is worse than a figure a few
        minutes old, and is indistinguishable to the user from no budget at all."""
        from types import SimpleNamespace

        from app.store import budget as budget_module

        state = {"fail": False}
        good = SimpleNamespace(branches=(), label="good")

        def loader():
            if state["fail"]:
                raise RuntimeError("sheets unavailable")
            return good

        cache = budget_module._CachedWorkbook(loader, ttl_seconds=1)
        state["fail"] = True
        cache._tried_at -= 5
        assert cache.data.label == "good"


class TestPipelineBudget:
    """Budget figures come from the tracker, whatever the model says.

    These used to assert the model was never called on a budget turn. Since the
    plan-execute-compose refactor it is called to word the answer, so the
    protection is no longer "no prompt" but the output guard: a figure that is
    not in the facts is rejected and the deterministic sentence is sent instead.
    Asserting the mechanism hid the fact that the mechanism had changed.
    """

    def test_an_invented_budget_figure_never_reaches_the_user(
        self, corpus, store: XlsxBudgetStore
    ) -> None:
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
        assert model.prompts, "the model is consulted for wording"
        # ...and overruled, because 99999 is not in the facts it was given.
        assert answer.source == DETERMINISTIC
        assert answer.route.intent is Intent.BUDGET
        assert "99999" not in answer.text
        assert "Milton Keynes" in answer.text
        assert "448" in answer.text or "448.32" in answer.text

    def test_a_sticky_follow_up_is_answered_for_the_new_country(
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
        # The model insisted on Canada; the tracker said United Kingdom and won.
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


class TestCacheAge:
    """Staleness has to be visible, because the health flag cannot show it.

    ``budget: true`` is decided once at startup and never changes, so a sheet
    that becomes unreadable later leaves the service looking healthy while the
    figures it serves get older.
    """

    def test_age_keeps_growing_while_refreshes_fail(self) -> None:
        from app.store.budget import _CachedWorkbook, _load_workbook

        cache = _CachedWorkbook(lambda: _load_workbook(FIXTURE), ttl_seconds=300)

        def explode() -> object:
            raise RuntimeError("sheet unreachable")

        cache._loader = explode  # type: ignore[assignment]
        cache._read_at -= 900
        cache._tried_at -= 301

        assert cache.data.branches, "the last good figures are still served"
        # One clock for both "last read" and "last tried" reset this to zero on
        # a failed refresh, so ageing data looked permanently fresh.
        assert cache.age_seconds >= 900

    def test_a_successful_refresh_resets_the_age(self) -> None:
        from app.store.budget import _CachedWorkbook, _load_workbook

        cache = _CachedWorkbook(lambda: _load_workbook(FIXTURE), ttl_seconds=300)
        cache._read_at -= 900

        # The worker directly, not through `data`: reading the property starts
        # a thread and returns at once, so asserting on the result afterwards
        # would be racing it.
        cache._refresh()

        assert cache.age_seconds < 5

    def test_a_slow_sheet_does_not_block_the_answer(self) -> None:
        """The regression that took production down for a turn.

        Refreshing inside the request meant a hung Sheets read held both the
        answer and the lock until Cloud Run killed the turn at sixty seconds.
        The user saw the assistant stop after "Looking that up...".
        """
        import threading
        import time as timing

        from app.store.budget import _CachedWorkbook, _load_workbook

        good = _load_workbook(FIXTURE)
        release = threading.Event()

        def slow() -> object:
            release.wait(10)
            return good

        cache = _CachedWorkbook(lambda: good, ttl_seconds=1)
        cache._loader = slow  # type: ignore[assignment]
        cache._tried_at -= 5

        started = timing.monotonic()
        served = cache.data
        elapsed = timing.monotonic() - started
        release.set()

        assert elapsed < 0.5, "the answer waited on the spreadsheet"
        assert served is good, "the figures already in hand are served meanwhile"
