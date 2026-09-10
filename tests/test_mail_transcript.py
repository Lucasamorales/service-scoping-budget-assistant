"""Request emails: short résumé body plus a PDF of the conversation."""

from __future__ import annotations

import re
from pathlib import Path

from app.knowledge.catalog import load_catalog
from app.knowledge.manifest import Manifest
from app.orchestrator.history import HistoryTurn
from app.store.audit import AuditEvent, JsonlAuditStore
from app.store.contacts import load_contacts
from app.store.mail import MailMessage, MailResult, NullMailer
from app.tools.email_template import TEMPLATE_DIR
from app.tools.mail import build_request_email, send_request_email
from app.tools.transcript import (
    TranscriptTurn,
    build_transcript,
    render_transcript_pdf,
    render_transcript_text,
    transcript_attachment,
)


class CapturingMailer:
    def __init__(self, from_address: str = "Acme Scoping <sender@example.com>") -> None:
        self.messages: list[MailMessage] = []
        self.from_address = from_address

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
        assert "abc123def456" in draft.body
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
        # £100, not 100.00 GBP. This was the one place the shared money format
        # never reached, so the email disagreed with every other surface.
        assert "£100" in draft.body
        assert "100.00 GBP" not in draft.body
        assert "purchase order" in draft.body.lower()

    def test_the_amount_leads_the_subject_for_the_person_approving_it(self) -> None:
        """A phone shows about thirty-five characters of a subject, and the
        figure is what decides whether this gets opened now or later."""
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
        assert draft.subject.startswith("£100 PO:")
        assert "Acme London" in draft.subject


class TestBothPartsAgree:
    """HTML and plain text are built from one set of values.

    Several of these recipients will only ever see the text part — it is the
    fallback, not a courtesy — so the two saying different things would be a
    silent way for one reader to approve something another was never shown.
    """

    def _draft(self, note: str = "Reopening push, needs artwork by the 26th."):
        return build_request_email(
            kind="email_cm_po",
            contact=_contact(),
            item=_item(),
            requester="Alex",
            country="United Kingdom",
            branch="Acme London",
            quote_amount=100.0,
            currency="GBP",
            note=note,
            conversation_id="abc123def456",
            from_address="Acme Scoping <sender@example.com>",
        )

    def test_both_parts_are_produced(self) -> None:
        draft = self._draft()
        assert draft.body.strip()
        assert draft.html.lstrip().startswith("<!--") or "<html" in draft.html

    def test_the_figure_and_the_reference_appear_in_both(self) -> None:
        draft = self._draft()
        for part in (draft.body, draft.html):
            assert "£100" in part
            assert "abc123def456" in part
            assert "Alex" in part

    def test_the_requesters_words_survive_into_both(self) -> None:
        draft = self._draft("Radio deal collapses without outdoor support.")
        assert "Radio deal collapses" in draft.body
        assert "Radio deal collapses" in draft.html

    def test_the_requesters_words_cannot_become_markup(self) -> None:
        """The context is typed into a web form by a person. Substituted raw it
        would be live HTML in somebody's mail client."""
        draft = self._draft('<script>alert("x")</script> & "quoted"')
        assert "<script>" not in draft.html
        assert "&lt;script&gt;" in draft.html
        assert "&amp;" in draft.html
        # The plain-text part is not markup, so it is left exactly as typed.
        assert '<script>alert("x")</script>' in draft.body

    def test_a_line_break_in_the_context_survives_as_one(self) -> None:
        draft = self._draft("First line.\nSecond line.")
        assert "First line.<br>Second line." in draft.html

    def test_no_placeholder_ever_reaches_a_reader(self) -> None:
        """An absent value renders as nothing. A recipient who reads
        "{{branch}}" learns nothing and distrusts the rest of the mail."""
        draft = build_request_email(
            kind="email_am",
            contact=_contact(),
            item=_item(),
            requester=None,
            country=None,
            branch=None,
            quote_amount=None,
            currency="GBP",
        )
        assert "{{" not in draft.html
        assert "{{" not in draft.body

    def test_the_html_part_reaches_the_provider(self) -> None:
        mailer = CapturingMailer()
        send_request_email(mailer, self._draft())
        assert mailer.messages[0].html


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


class TestVerdictsInTheTranscript:
    def test_a_verdict_rides_along_with_the_turn_that_reached_it(
        self, tmp_path: Path
    ) -> None:
        store = JsonlAuditStore(tmp_path)
        store.append(
            AuditEvent(
                conversation_id="c1",
                kind="turn",
                payload={
                    "user_message": "can we do a billboard",
                    "assistant_message": "That one needs a quote.",
                    "status": "quote_required",
                },
            )
        )
        turns = build_transcript(conversation_id="c1", audit_log=store)
        user, assistant = turns
        assert assistant.verdict == "quote_required"
        # The question carries none. A verdict is what the answer reached, and
        # putting it on the asking turn would credit the person with it.
        assert user.verdict is None

    def test_a_turn_that_reached_no_verdict_carries_none(self, tmp_path: Path) -> None:
        """The common case, not the exception. Budget answers, clarifying
        questions and greetings all resolve no service, so a transcript with
        pills on some turns and nothing on others is the normal rendering."""
        store = JsonlAuditStore(tmp_path)
        store.append(
            AuditEvent(
                conversation_id="c2",
                kind="turn",
                payload={
                    "user_message": "what is left in the budget",
                    "assistant_message": "£1,240 of £2,000.",
                    "status": None,
                },
            )
        )
        _, assistant = build_transcript(conversation_id="c2", audit_log=store)
        assert assistant.verdict is None

    def test_the_client_history_fallback_claims_no_verdicts(self) -> None:
        """It never held any — only the audit log records them."""
        turns = build_transcript(
            conversation_id=None,
            audit_log=None,
            history=(HistoryTurn("assistant", "That one needs a quote."),),
        )
        assert all(turn.verdict is None for turn in turns)


class TestPdfRendering:
    def _turns(self, count: int = 4) -> tuple[TranscriptTurn, ...]:
        return tuple(
            TranscriptTurn(
                at=f"2026-08-20T1{4 + index // 6}:{index:02d}:00+00:00",
                role="user" if index % 2 == 0 else "assistant",
                content=f"Message {index}. " + "Some words to fill the block out. " * 4,
                verdict="quote_required" if index % 2 else None,
            )
            for index in range(count)
        )

    def test_the_pound_sign_survives(self) -> None:
        """The brand faces are embedded, so the document is Unicode.

        It used to be rendered with fpdf2's core fonts, which are Latin-1: the
        pound sign came through only because cp1252 happens to contain it, and
        an em dash or a curly quote was replaced with a question mark.
        """
        data = render_transcript_pdf(
            (TranscriptTurn(at="", role="assistant", content="Priced at £350 — roughly."),),
            title="t",
        )
        assert data.startswith(b"%PDF")

    def test_an_em_dash_no_longer_breaks_the_render(self) -> None:
        """A crash here is not cosmetic: the whole PDF is abandoned and the
        email goes out with a .txt attachment instead."""
        filename, data, mime = transcript_attachment(
            (TranscriptTurn(at="", role="user", content="— dashes — everywhere —"),),
            title="Quote needed — Photoshoots",
            filename_stem="conversation-test",
            kind="email_am",
        )
        assert filename.endswith(".pdf")
        assert mime == "application/pdf"
        assert data.startswith(b"%PDF")

    def test_a_long_conversation_paginates(self) -> None:
        import pypdfium2

        data = render_transcript_pdf(self._turns(40), title="t", kind="email_cm_po")
        assert len(pypdfium2.PdfDocument(data)) > 1

    def test_the_closing_line_never_gets_a_page_to_itself(self) -> None:
        """It used to. The conversation filled the page to within a few
        millimetres and the only thing that moved was the line announcing the
        conversation had finished, which read as a printing fault.
        """
        import pypdfium2

        for count in range(2, 26):
            doc = pypdfium2.PdfDocument(
                render_transcript_pdf(self._turns(count), title="t", kind="email_cm_po")
            )
            last = doc[len(doc) - 1].get_textpage().get_text_range()
            assert "REQUESTER" in last or "SCOPING ASSISTANT" in last, (
                f"{count} turns left a page carrying only the closing line"
            )

    def test_an_empty_conversation_still_renders(self) -> None:
        data = render_transcript_pdf((), title="t", kind="email_am")
        assert data.startswith(b"%PDF")


class TestNothingInternalReachesTheReader:
    """The recipient is a country manager, not an operator of this system."""

    def _draft(self, **kw):
        base = dict(
            kind="email_am",
            contact=_contact(),
            item=_item(),
            requester="Alex",
            role="Marketing Executive",
            country="United Kingdom",
            branch="Acme London",
            quote_amount=None,
            currency="GBP",
            note="Needed for the reopening.",
        )
        return build_request_email(**{**base, **kw})

    def test_the_verdict_is_named_the_way_the_chat_names_it(self) -> None:
        """Not the spreadsheet's own code. Two of the four verdicts are stored
        as the single letter "Y" or "N", and the in-scope gloss beside it does
        not parse: "We can do it and is within our scope"."""
        draft = self._draft()
        for part in (draft.body, draft.html):
            assert "In scope" in part
            assert "Y —" not in part
            assert "Y --" not in part
            assert "and is within our scope" not in part

    def test_a_missing_venue_is_not_called_unknown(self) -> None:
        """The sign-in leaves the branch optional, so this is the common case,
        and "unknown, United Kingdom" reads as a fault rather than a blank."""
        draft = self._draft(branch=None)
        for part in (draft.body, draft.html):
            assert "unknown" not in part.lower()
            assert "United Kingdom" in part
        assert "at unknown" not in draft.html

    def test_a_missing_role_leaves_no_dangling_punctuation(self) -> None:
        draft = self._draft(role=None)
        assert "Alex," not in draft.body

    def test_an_absent_asset_is_removed_rather_than_left_empty(self) -> None:
        """src="" is not the absence of an image — a mail client draws a broken
        icon for it, and one of those in the header band is worse than no logo.
        """
        draft = self._draft(asset_base_url="")
        assert 'src=""' not in draft.html
        assert 'href=""' not in draft.html
        assert "<img" not in draft.html

    def test_an_asset_base_puts_the_logo_back(self) -> None:
        draft = self._draft(asset_base_url="https://assistant.example.com")
        assert "https://assistant.example.com/widget/assets/acme-logo-email.png" in draft.html

    def test_the_templates_own_documentation_is_not_sent(self) -> None:
        """It is a token reference for whoever edits the file. Left in, it gets
        filled with real values — a second, invisible copy of everything the
        requester typed."""
        draft = self._draft()
        assert "MUST BE HTML-ESCAPED" not in draft.html
        assert draft.html.count("Needed for the reopening.") == 1


class TestTheTemplatesStayEmailSafe:
    def _html(self, base: str) -> str:
        return build_request_email(
            kind="email_cm_po",
            contact=_contact(),
            item=_item(),
            requester="Alex",
            country="United Kingdom",
            branch="Acme London",
            quote_amount=100.0,
            currency="GBP",
            note="n",
            asset_base_url=base,
        ).html

    def test_the_faces_are_declared_twice_on_purpose(self) -> None:
        """A <link> and an embedded block reach different clients — several
        honour one and drop the other — so both together land more often."""
        html_body = self._html("https://assistant.example.com")
        assert '<link href="https://assistant.example.com' in html_body
        assert "@font-face" in html_body
        assert html_body.count("inter-display-900.woff2") >= 1

    def test_every_face_url_is_absolute(self) -> None:
        """An email has no origin, so a relative path resolves against nothing."""
        html_body = self._html("https://assistant.example.com")
        for face in re.findall(r"src:url\('([^']+)'\)", html_body):
            assert face.startswith("https://"), face

    def test_no_faces_are_declared_without_somewhere_to_fetch_them(self) -> None:
        html_body = self._html("")
        assert "@font-face" not in html_body
        assert "<style" not in html_body

    def test_the_only_stylesheet_is_the_faces(self) -> None:
        """Everything else is inline CSS, which is what keeps Gmail from
        stripping the design. The font block is the one exception, and it is
        progressive enhancement — nothing depends on it arriving."""
        for kind in ("email_am", "email_cm_po", "email_am_variable"):
            source = (TEMPLATE_DIR / f"{kind}.html").read_text(encoding="utf-8")
            blocks = re.findall(r"<style\b[^>]*>(.*?)</style>", source, re.DOTALL)
            assert len(blocks) == 1, kind
            assert "@font-face" in blocks[0]
            assert "{" in blocks[0] and "@media" not in blocks[0]
