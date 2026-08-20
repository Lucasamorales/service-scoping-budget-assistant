"""Business flows: CTAs, quoting, confirm → mail draft, contacts, audit."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.knowledge.chunking import chunk_service_item
from app.knowledge.index import KnowledgeIndex
from app.orchestrator.llm import DETERMINISTIC
from app.orchestrator.pipeline import Pipeline
from app.orchestrator.router import Intent
from app.store.audit import JsonlAuditStore
from app.store.budget import XlsxBudgetStore
from app.store.contacts import load_contacts
from app.store.mail import NullMailer
from app.store.quote import load_quote_store
from app.store.roster import load_roster
from app.tools.flows import SessionIdentity
from tests.test_pipeline import RecordingModel

BUDGET_XLSX = Path("fixtures/budget/acme_scope_db.xlsx")
CONTACTS = Path("fixtures/contacts/country_ams.json")
RATE_CARD = Path("fixtures/quote/rate_card.json")


@pytest.fixture(scope="module")
def flow_pipeline(corpus, tmp_path_factory) -> Pipeline:
    chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
    audit_dir = tmp_path_factory.mktemp("audit")
    return Pipeline(
        corpus.catalog,
        KnowledgeIndex.build(chunks),
        model=RecordingModel("I invented a price of 99999."),
        budget_store=XlsxBudgetStore(BUDGET_XLSX),
        quote_store=load_quote_store(RATE_CARD),
        contacts=load_contacts(CONTACTS),
        roster=load_roster(BUDGET_XLSX),
        mailer=NullMailer(),
        audit_log=JsonlAuditStore(audit_dir),
        branches=tuple(t.name for t in XlsxBudgetStore(BUDGET_XLSX).branches()),
    )


class TestContactsAndRoster:
    def test_uk_am_is_lucas(self) -> None:
        contacts = load_contacts(CONTACTS)
        robin = contacts.for_country("United Kingdom", role="account_manager")
        assert robin is not None
        assert robin.email == "robin@example.com"

    def test_canada_cm_is_charlie(self) -> None:
        contacts = load_contacts(CONTACTS)
        charlie = contacts.for_country("Canada", role="country_manager")
        assert charlie is not None
        assert charlie.email == "charlie@example.com"

    def test_international_does_not_auto_route(self) -> None:
        contacts = load_contacts(CONTACTS)
        assert contacts.for_country("International") is None

    def test_roster_loads_people(self) -> None:
        roster = load_roster(BUDGET_XLSX)
        assert roster is not None
        assert roster.find_by_name("Samantha Low") is not None


class TestInScopeFlow:
    def test_in_scope_offers_am_cta(self, flow_pipeline: Pipeline) -> None:
        answer = flow_pipeline.answer(
            "campaign wrap-ups",
            identity=SessionIdentity(country="United Kingdom", branch="Acme Milton Keynes"),
        )
        assert answer.status is not None
        assert answer.source == DETERMINISTIC
        assert answer.actions
        assert answer.next_state.pending_action_kind == "email_am"
        assert "Robin" in answer.text or "Account Manager" in answer.text
        assert "99999" not in answer.text


class TestQuoteFlow:
    def test_on_demand_uses_rate_card_not_model(self, flow_pipeline: Pipeline) -> None:
        answer = flow_pipeline.answer(
            "can we order some merch",
            identity=SessionIdentity(country="Canada", branch="Acme Oakville"),
        )
        assert answer.route.intent is Intent.SCOPING or answer.status is not None
        assert answer.source == DETERMINISTIC
        assert "99999" not in answer.text
        assert answer.actions
        assert answer.next_state.pending_action_kind in {"email_cm_po", "email_am_variable"}
        # Merch is on the rate card as Tier 1 (£100).
        if answer.next_state.pending_action_kind == "email_cm_po":
            assert answer.next_state.pending_quote_amount == 100.0

    def test_variable_tier_routes_to_am(self, flow_pipeline: Pipeline) -> None:
        answer = flow_pipeline.answer(
            "site visits travel accommodation",
            identity=SessionIdentity(country="United Kingdom"),
        )
        assert answer.source == DETERMINISTIC
        assert "manual" in answer.text.lower() or "Account Manager" in answer.text
        assert answer.next_state.pending_action_kind == "email_am_variable"


class TestConfirmMail:
    def test_yes_produces_draft_when_mail_not_configured(self, flow_pipeline: Pipeline) -> None:
        first = flow_pipeline.answer(
            "campaign wrap-ups",
            identity=SessionIdentity(
                subject="Alex",
                country="United Kingdom",
                branch="Acme Milton Keynes",
            ),
        )
        second = flow_pipeline.answer(
            "Yes",
            first.next_state,
            identity=SessionIdentity(
                subject="Alex",
                country="United Kingdom",
                branch="Acme Milton Keynes",
            ),
        )
        assert second.source == DETERMINISTIC
        assert second.next_state.pending_action_kind is None
        assert "Robin" in second.text
        assert "draft" in second.text.lower() or "isn't connected" in second.text.lower()
        assert "Recent conversation" not in second.text
        assert "attached" in second.text.lower()
        events = flow_pipeline.audit_log.read(second.next_state.conversation_id)  # type: ignore[union-attr]
        email = events[-1].payload.get("email") or {}
        assert str(email.get("attachment", "")).endswith(".pdf")

    def test_no_cancels(self, flow_pipeline: Pipeline) -> None:
        first = flow_pipeline.answer(
            "campaign wrap-ups",
            identity=SessionIdentity(country="France"),
        )
        second = flow_pipeline.answer(
            "No", first.next_state, identity=SessionIdentity(country="France")
        )
        assert "won't send" in second.text.lower() or "No problem" in second.text

    def test_asks_for_country_when_session_has_none(self, flow_pipeline: Pipeline) -> None:
        first = flow_pipeline.answer("can we do a billboard?", identity=SessionIdentity())
        assert first.next_state.pending_action_kind == "email_cm_po"
        second = flow_pipeline.answer("Yes", first.next_state, identity=SessionIdentity())
        assert second.next_state.pending_needs_country is True
        assert "Which country" in second.text
        assert any(action.label == "United Kingdom" for action in second.actions)

        third = flow_pipeline.answer(
            "United Kingdom",
            second.next_state,
            identity=SessionIdentity(),
        )
        assert third.next_state.pending_action_kind is None
        assert third.next_state.pending_needs_country is False
        assert "Charlie" in third.text


class TestAudit:
    def test_turns_are_logged(self, flow_pipeline: Pipeline) -> None:
        answer = flow_pipeline.answer(
            "campaign wrap-ups",
            identity=SessionIdentity(country="UK"),
        )
        assert answer.next_state.conversation_id
        events = flow_pipeline.audit_log.read(answer.next_state.conversation_id)  # type: ignore[union-attr]
        assert events
        assert events[-1].kind == "turn"
