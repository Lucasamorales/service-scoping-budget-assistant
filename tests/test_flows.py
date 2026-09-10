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
from app.store.quote import QuoteStore, load_quote_store
from app.store.roster import load_roster
from app.tools.flows import SessionIdentity
from tests.test_pipeline import RecordingModel

BUDGET_XLSX = Path("fixtures/budget/acme_scope_db.xlsx")
CONTACTS = Path("fixtures/contacts/country_ams.json")
RATE_CARD = Path("fixtures/quote/rate_card.json")


def build_pipeline(corpus, audit_dir: Path, quote_store: QuoteStore | None) -> Pipeline:
    chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
    return Pipeline(
        corpus.catalog,
        KnowledgeIndex.build(chunks),
        model=RecordingModel("I invented a price of 99999."),
        budget_store=XlsxBudgetStore(BUDGET_XLSX),
        quote_store=quote_store,
        contacts=load_contacts(CONTACTS),
        roster=load_roster(BUDGET_XLSX),
        mailer=NullMailer(),
        audit_log=JsonlAuditStore(audit_dir),
        branches=tuple(t.name for t in XlsxBudgetStore(BUDGET_XLSX).branches()),
    )


@pytest.fixture(scope="module")
def flow_pipeline(corpus, tmp_path_factory) -> Pipeline:
    return build_pipeline(
        corpus, tmp_path_factory.mktemp("audit"), load_quote_store(RATE_CARD)
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
        # The Scope tab puts Merch at Tier 3 (£350). The fixture used to say
        # Tier 1, and this assertion used to agree with it.
        if answer.next_state.pending_action_kind == "email_cm_po":
            assert answer.next_state.pending_quote_amount == 350.0

    def test_variable_tier_routes_to_am(self, corpus, tmp_path) -> None:
        """A service priced ``Variable`` has no number, so it goes to a human.

        The store is built here rather than loaded, because which services are
        Variable is a business decision that changes: every row on the Scope
        tab currently carries a numeric tier, so loading the real card would
        leave this rule untested and look like it still passed. The rule is
        what matters, not the roster of services it happens to apply to.
        """
        item = (
            "strategic-support--site-visits-if-required"
            "-travel-accommodation-to-be-paid-for-by-acme"
        )
        pipeline = build_pipeline(
            corpus,
            tmp_path,
            QuoteStore(
                currency="GBP",
                tiers={"1": 100.0, "2": 200.0, "3": 350.0, "Variable": "Variable"},
                services={item: "Variable"},
            ),
        )
        answer = pipeline.answer(
            "site visits travel accommodation",
            identity=SessionIdentity(country="United Kingdom"),
        )
        assert answer.source == DETERMINISTIC
        assert "manual" in answer.text.lower() or "Account Manager" in answer.text
        assert answer.next_state.pending_action_kind == "email_am_variable"


class TestConfirmMail:
    ALEX = SessionIdentity(
        subject="Alex", country="United Kingdom", branch="Acme Milton Keynes"
    )

    def test_a_yes_without_context_asks_for_it_rather_than_sending(
        self, flow_pipeline: Pipeline
    ) -> None:
        """Context is required, and the API is what enforces it.

        The widget disables its own submit until something is typed, but the
        widget is not the only way to reach this endpoint, and a rule kept only
        by a browser is not a rule.
        """
        first = flow_pipeline.answer("campaign wrap-ups", identity=self.ALEX)
        second = flow_pipeline.answer("Yes", first.next_state, identity=self.ALEX)

        assert "context" in second.text.lower()
        assert second.next_state.pending_action_kind == "email_am", "the CTA stays alive"
        events = flow_pipeline.audit_log.read(second.next_state.conversation_id)  # type: ignore[union-attr]
        assert not any(event.payload.get("email") for event in events), "nothing was sent"

    def test_yes_produces_draft_when_mail_not_configured(self, flow_pipeline: Pipeline) -> None:
        first = flow_pipeline.answer(
            "campaign wrap-ups",
            identity=self.ALEX,
        )
        second = flow_pipeline.answer(
            "Yes",
            first.next_state,
            identity=self.ALEX,
            note="Launch event in March, need these for the opening.",
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
        assert third.next_state.pending_needs_country is False
        # Country known, context still missing — so it asks rather than sends.
        # This branch used to call send() directly, which skipped the context
        # requirement entirely and mailed an empty "Why they are asking".
        assert third.next_state.pending_action_kind == "email_cm_po"
        assert "context" in third.text.lower()

        fourth = flow_pipeline.answer(
            "Yes",
            third.next_state,
            identity=SessionIdentity(),
            note="For the March reopening.",
        )
        assert fourth.next_state.pending_action_kind is None
        assert "Charlie" in fourth.text


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


class TestRequestContext:
    """The note typed into a send CTA, on its way to the email.

    Carried beside the confirmation rather than as it: the message stays "Yes"
    so the affirmative check keeps meaning what it says, and free prose about a
    launch event never has to parse as consent.
    """

    ALEX = SessionIdentity(
        subject="Alex", country="United Kingdom", branch="Acme Milton Keynes"
    )
    CONTEXT = "Launch event in March, we need these for the opening."

    def test_the_context_reaches_the_email_body(self, flow_pipeline: Pipeline) -> None:
        first = flow_pipeline.answer("campaign wrap-ups", identity=self.ALEX)
        second = flow_pipeline.answer(
            "Yes", first.next_state, identity=self.ALEX, note=self.CONTEXT
        )

        events = flow_pipeline.audit_log.read(second.next_state.conversation_id)  # type: ignore[union-attr]
        email = next(e.payload["email"] for e in reversed(events) if e.payload.get("email"))
        assert email["note"] == self.CONTEXT

    def test_whitespace_alone_is_not_context(self, flow_pipeline: Pipeline) -> None:
        """Otherwise the requirement is satisfied by pressing space."""
        first = flow_pipeline.answer("campaign wrap-ups", identity=self.ALEX)
        second = flow_pipeline.answer(
            "Yes", first.next_state, identity=self.ALEX, note="   \n  "
        )

        assert "context" in second.text.lower()
        assert second.next_state.pending_action_kind == "email_am"

    def test_the_send_cta_offers_a_box_to_type_it_in(self, flow_pipeline: Pipeline) -> None:
        answer = flow_pipeline.answer("campaign wrap-ups", identity=self.ALEX)

        yes = next(a for a in answer.actions if a.id == "confirm_yes")
        no = next(a for a in answer.actions if a.id == "confirm_no")
        assert yes.kind == "note", "the yes opens a box rather than firing"
        assert yes.prompt and "context" in yes.prompt.lower()
        assert yes.placeholder, "an example, because people copy what they are shown"
        assert yes.message == "Yes", "the confirmation itself stays a plain yes"
        assert no.kind == "message", "declining needs no context"

    def test_a_quote_cta_asks_for_context_too(self, flow_pipeline: Pipeline) -> None:
        """Every path that sends an email, not just the purchase order."""
        answer = flow_pipeline.answer(
            "can we order some merch",
            identity=SessionIdentity(country="Canada", branch="Acme Oakville"),
        )

        yes = next(a for a in answer.actions if a.id == "confirm_yes")
        assert yes.kind == "note"


class TestTheEmailIsWiredToItsEnvironment:
    """Two values reach the templates from outside the orchestrator.

    Both are easy to leave dangling — nothing in between has any use for them,
    and the mail still sends without them, so a broken wire shows up only as a
    missing logo and an empty "Sent from" line in somebody's inbox. Driven
    through ``answer`` rather than around it, because the wiring is the thing
    under test.
    """

    ALEX = SessionIdentity(subject="Alex", role="marketing", country="United Kingdom")

    @pytest.fixture(scope="class")
    @classmethod
    def sent(cls, corpus, tmp_path_factory):
        from app.store.mail import MailMessage, MailResult

        class Capturing:
            from_address = "Acme Scoping <sender@example.org>"

            def __init__(self) -> None:
                self.messages: list[MailMessage] = []

            def send(self, message: MailMessage) -> MailResult:
                self.messages.append(message)
                return MailResult(sent=True, provider_id="x", detail="sent")

        mailer = Capturing()
        chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
        pipeline = Pipeline(
            corpus.catalog,
            KnowledgeIndex.build(chunks),
            model=RecordingModel("ignored"),
            quote_store=load_quote_store(RATE_CARD),
            contacts=load_contacts(CONTACTS),
            mailer=mailer,
            audit_log=JsonlAuditStore(tmp_path_factory.mktemp("audit")),
            asset_base_url="https://assistant.example.com",
        )
        first = pipeline.answer("campaign wrap-ups", identity=cls.ALEX)
        assert first.next_state.pending_action_kind == "email_am"
        pipeline.answer(
            "Yes",
            first.next_state,
            identity=cls.ALEX,
            note="Needed before the country review on the 3rd.",
        )
        assert mailer.messages, "the confirmation never reached the mailer"
        return mailer.messages[0]

    def test_the_asset_urls_are_absolute_and_point_at_this_service(self, sent) -> None:
        base = "https://assistant.example.com/widget/assets"
        assert f"{base}/acme-logo-email.png" in sent.html
        assert f"{base}/email-fonts.css" in sent.html

    def test_the_sending_identity_reaches_the_footer(self, sent) -> None:
        """It is the mailer's own fact, and the footer is where the design puts
        it — so a reader can see the mail came from a machine, not a person."""
        assert "sender@example.org" in sent.body
        assert "sender@example.org" in sent.html

    def test_the_requesters_context_travels(self, sent) -> None:
        assert "country review on the 3rd" in sent.body
        assert "country review on the 3rd" in sent.html

    def test_both_parts_and_the_pdf_go_together(self, sent) -> None:
        assert sent.body.strip()
        assert sent.html.strip()
        assert sent.attachments[0].content.startswith(b"%PDF")
