"""Request emails: short résumé body plus a PDF of the conversation."""

from __future__ import annotations

from pathlib import Path

from app.knowledge.catalog import load_catalog
from app.knowledge.manifest import Manifest
from app.orchestrator.history import HistoryTurn
from app.store.audit import AuditEvent, JsonlAuditStore
from app.store.contacts import load_contacts
from app.store.mail import MailMessage, MailResult, NullMailer
from app.tools.mail import build_request_email, send_request_email
from app.tools.transcript import (
    TranscriptTurn,
    build_transcript,
    render_transcript_pdf,
    render_transcript_text,
)


class CapturingMailer:
    def __init__(self) -> None:
        self.messages: list[MailMessage] = []

    def send(self, message: MailMessage) -> MailResult:
        self.messages.append(message)
        return MailResult(sent=True, provider_id="test-id", detail="sent")


def _item():
    catalog = load_catalog(Manifest.load(Path("documents"))).catalog
    item = catalog.get("copywriting--emails")
    assert item is not None
    return item


def _contact():
    contact = load_contacts(Path("fixtures/contacts/country_ams.json")).for_country(
        "United Kingdom", role="account_manager"
    )
    assert contact is not None
    return contact


class TestResumeBody:
    def test_body_is_a_summary_not_the_thread(self) -> None:
        history = (
            HistoryTurn("user", "Can we do campaign wrap-ups?"),
            HistoryTurn("assistant", "Yes — that is in scope." + (" extra" * 200)),
        )
        draft = build_request_email(
            kind="email_am",
            contact=_contact(),
            item=_item(),
            requester="Alex",
            country="United Kingdom",
            branch="Acme London",
            quote_amount=None,
            currency="GBP",
            history=history,
            conversation_id="abc123def456",
        )
        assert "Recent conversation" not in draft.body
        assert "extra extra" not in draft.body
        assert "Alex" in draft.body
        assert "United Kingdom" in draft.body
        assert "Acme London" in draft.body
        assert "attached as a PDF" in draft.body
        assert "Reference: abc123def456" in draft.body
        assert draft.attachments
        assert draft.attachments[0].filename.endswith(".pdf")
        assert draft.attachments[0].content.startswith(b"%PDF")

    def test_po_email_states_the_amount_and_the_ask(self) -> None:
        draft = build_request_email(
            kind="email_cm_po",
            contact=_contact(),
            item=_item(),
            requester="Alex",
            country="United Kingdom",
            branch="Acme London",
            quote_amount=100.0,
            currency="GBP",
        )
        assert "100.00 GBP" in draft.body
        assert "purchase order" in draft.body.lower()


class TestTranscriptSource:
    def test_audit_log_beats_clipped_client_history(self, tmp_path: Path) -> None:
        store = JsonlAuditStore(tmp_path)
        store.append(
            AuditEvent(
                conversation_id="conv1",
                kind="turn",
                payload={
                    "user_message": "the real long request from the database " * 20,
                    "assistant_message": "The catalog answer.",
                },
                at="2026-08-20T12:00:00+00:00",
            )
        )
        history = (HistoryTurn("user", "clipped"),)
        turns = build_transcript(
            conversation_id="conv1",
            audit_log=store,
            history=history,
        )
        assert turns[0].content.startswith("the real long request")
        assert "clipped" not in turns[0].content

    def test_history_is_used_when_the_log_is_empty(self) -> None:
        history = (HistoryTurn("user", "only in the browser"),)
        turns = build_transcript(
            conversation_id="missing",
            audit_log=None,
            history=history,
        )
        assert turns[0].content == "only in the browser"

    def test_pdf_contains_the_unclipped_turn(self) -> None:
        long = "please handle translation for all landing pages " * 30
        turns = (TranscriptTurn(at="2026-08-20T12:00:00+00:00", role="user", content=long),)
        pdf = render_transcript_pdf(
            turns,
            title="Acme request",
            requester="Alex",
            country="United Kingdom",
            branch="Acme London",
            service="Translation",
            conversation_id="conv1",
        )
        assert pdf.startswith(b"%PDF")
        text = render_transcript_text(
            turns,
            title="Acme request",
            requester="Alex",
            conversation_id="conv1",
        )
        assert long.strip() in text
        assert "400" not in text or long.strip() in text


class TestSendAttaches:
    def test_resend_payload_carries_the_pdf(self) -> None:
        mailer = CapturingMailer()
        draft = build_request_email(
            kind="email_am",
            contact=_contact(),
            item=_item(),
            requester="Alex",
            country="United Kingdom",
            branch="Acme London",
            quote_amount=None,
            currency="GBP",
            history=(HistoryTurn("user", "campaign wrap-ups"),),
            conversation_id="deadbeef",
        )
        result = send_request_email(mailer, draft)
        assert result.sent
        sent = mailer.messages[0]
        assert sent.attachments
        assert sent.attachments[0].filename.endswith(".pdf")
        assert "Recent conversation" not in sent.body

    def test_null_mailer_does_not_claim_a_send(self) -> None:
        draft = build_request_email(
            kind="email_am",
            contact=_contact(),
            item=_item(),
            requester="Alex",
            country="United Kingdom",
            branch=None,
            quote_amount=None,
            currency="GBP",
        )
        result = send_request_email(NullMailer(), draft)
        assert not result.sent
