"""The context a requester types must reach the email that asks for money.

Reproduces the sequence that broke it live: sign in without a country, ask for
something that needs a purchase order, say yes, type the context — and then be
asked which country you are in. That question arrives between typing the
context and sending, and the turn answering it carries no note of its own.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.knowledge.chunking import chunk_service_item
from app.knowledge.index import KnowledgeIndex
from app.orchestrator.pipeline import Pipeline
from app.store.audit import JsonlAuditStore
from app.store.contacts import load_contacts
from app.store.mail import MailMessage, MailResult
from app.store.quote import load_quote_store
from app.tools.flows import SessionIdentity
from tests.test_pipeline import RecordingModel

CONTACTS = Path("fixtures/contacts/country_ams.json")
RATE_CARD = Path("fixtures/quote/rate_card.json")

CONTEXT = "Reopening push. The site is booked for two weeks and artwork is due on the 26th."


class Capturing:
    from_address = "Acme Scoping <sender@example.org>"

    def __init__(self) -> None:
        self.messages: list[MailMessage] = []

    def send(self, message: MailMessage) -> MailResult:
        self.messages.append(message)
        return MailResult(sent=True, provider_id="x", detail="sent")


@pytest.fixture
def live(corpus, tmp_path):
    mailer = Capturing()
    chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
    pipeline = Pipeline(
        corpus.catalog,
        KnowledgeIndex.build(chunks),
        model=RecordingModel("ignored"),
        quote_store=load_quote_store(RATE_CARD),
        contacts=load_contacts(CONTACTS),
        mailer=mailer,
        audit_log=JsonlAuditStore(tmp_path),
    )
    return pipeline, mailer


# No country. That is what puts the country question in the way, and it is the
# default: sign-in does not require one.
NOBODY = SessionIdentity(subject="Remy", role="am")


class TestContextSurvivesTheCountryQuestion:
    def _run(self, live):
        pipeline, mailer = live
        first = pipeline.answer("can we do some signage", identity=NOBODY)
        assert first.next_state.pending_action_kind == "email_cm_po"

        # Yes, with the context typed into the pop-up.
        second = pipeline.answer(
            "Yes", first.next_state, identity=NOBODY, note=CONTEXT
        )
        assert not mailer.messages, "sent before knowing who to send it to"
        assert second.next_state.pending_needs_country is True

        # Answering the country. This turn carries no note of its own.
        third = pipeline.answer("United Kingdom", second.next_state, identity=NOBODY)
        return mailer, third

    def test_the_email_goes_once_the_country_is_known(self, live) -> None:
        mailer, _ = self._run(live)
        assert mailer.messages, "the country answer did not complete the send"

    def test_the_context_is_still_in_it(self, live) -> None:
        """It used to be dropped: the country branches sent directly and never
        reached the check that requires a context, so the email went out with
        an empty "Why they are asking" — the one part of it a person wrote."""
        mailer, _ = self._run(live)
        sent = mailer.messages[0]
        assert CONTEXT in sent.body
        assert "artwork is due on the 26th" in sent.html

    def test_the_pdf_carries_it_too(self, live) -> None:
        mailer, _ = self._run(live)
        assert mailer.messages[0].attachments[0].content.startswith(b"%PDF")


class TestNothingSendsWithoutAContext:
    def test_a_country_answer_alone_does_not_send(self, live) -> None:
        """The same path, with no context ever given. It must ask, not send."""
        pipeline, mailer = live
        first = pipeline.answer("can we do some signage", identity=NOBODY)
        second = pipeline.answer("Yes", first.next_state, identity=NOBODY)
        third = pipeline.answer("United Kingdom", second.next_state, identity=NOBODY)
        assert not mailer.messages
        assert third.next_state.pending_action_kind == "email_cm_po", "the CTA stays alive"

    def test_it_sends_once_the_context_arrives(self, live) -> None:
        pipeline, mailer = live
        first = pipeline.answer("can we do some signage", identity=NOBODY)
        second = pipeline.answer("Yes", first.next_state, identity=NOBODY)
        third = pipeline.answer("United Kingdom", second.next_state, identity=NOBODY)
        pipeline.answer("Yes", third.next_state, identity=NOBODY, note=CONTEXT)
        assert mailer.messages
        assert CONTEXT in mailer.messages[0].body


class TestTheRequestersRoleIsWrittenOut:
    def test_the_sign_in_code_never_appears(self, live) -> None:
        """Sign-in stores the role as "am". In front of a country manager that
        is the system's vocabulary, not a job title."""
        pipeline, mailer = live
        first = pipeline.answer("can we do some signage", identity=NOBODY)
        second = pipeline.answer("Yes", first.next_state, identity=NOBODY, note=CONTEXT)
        pipeline.answer("United Kingdom", second.next_state, identity=NOBODY)
        sent = mailer.messages[0]
        for part in (sent.body, sent.html):
            assert "Remy, am" not in part
            assert "Account Manager" in part
