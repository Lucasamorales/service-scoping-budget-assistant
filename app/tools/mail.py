"""Build and send request emails after an explicit Yes in chat.

The body is a short résumé the Account or Country Manager can act on. The full
thread travels as a PDF attachment (plain text if PDF generation fails), built
from the audit log rather than the clipped browser history.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.types import ServiceItem
from app.orchestrator.history import HistoryTurn
from app.store.audit import AuditStore
from app.store.contacts import Contact
from app.store.mail import MailAttachment, Mailer, MailMessage, MailResult
from app.tools.transcript import build_transcript, transcript_attachment

__all__ = ["MailDraft", "build_request_email", "send_request_email"]

_ASK = {
    "email_am": "Please pick this up as an in-scope (free of charge) request.",
    "email_cm_po": "Please raise a purchase order for the amount below.",
    "email_am_variable": (
        "Please price this by hand — it is not on the standard rate card."
    ),
}


@dataclass(frozen=True, slots=True)
class MailDraft:
    contact: Contact
    subject: str
    body: str
    kind: str
    attachments: tuple[MailAttachment, ...] = field(default_factory=tuple)


def build_request_email(
    *,
    kind: str,
    contact: Contact,
    item: ServiceItem | None,
    requester: str | None,
    country: str | None,
    branch: str | None,
    quote_amount: float | None,
    currency: str,
    history: tuple[HistoryTurn, ...] = (),
    conversation_id: str | None = None,
    audit_log: AuditStore | None = None,
    role: str | None = None,
    current_message: str | None = None,
    note: str | None = None,
) -> MailDraft:
    service = item.display_name if item else "a marketing request"
    subject = {
        "email_am": f"Acme request: {service}",
        "email_cm_po": f"PO request: {service}",
        "email_am_variable": f"Manual quote needed: {service}",
    }.get(kind, f"Acme request: {service}")

    lines = [
        f"Hi {contact.name},",
        "",
        "A request came through the Acme Scoping Assistant. Summary:",
        "",
        f"From: {requester or 'unknown'}"
        + (f" ({role})" if role else ""),
        f"Country: {country or 'unknown'}",
        f"Branch: {branch or 'unknown'}",
        f"Service: {service}",
    ]
    if item is not None:
        lines.append(f"Status: {item.status_raw.strip()} — {item.status_meaning}")
    if quote_amount is not None:
        lines.append(f"Quoted amount: {quote_amount:,.2f} {currency}")
    ask = _ASK.get(kind, "Please take a look at this request.")
    stem = f"conversation-{_short_id(conversation_id)}"
    filename, content, mime = transcript_attachment(
        build_transcript(
            conversation_id=conversation_id,
            audit_log=audit_log,
            history=history,
            current_message=current_message,
        ),
        title=subject,
        filename_stem=stem,
        requester=requester,
        country=country,
        branch=branch,
        service=service,
        conversation_id=conversation_id,
    )
    attached = (
        "The full conversation is attached as a PDF."
        if filename.endswith(".pdf")
        else "The full conversation is attached as a text file (PDF could not be built)."
    )

    body_lines = [*lines]
    if note and note.strip():
        # Under its own heading, above the ask, because it is the one part of
        # this email a person wrote deliberately for the reader.
        #
        # Inserted as plain text into a plain-text body — Resend is sent
        # `"text"`, not `"html"`. If this email ever grows an HTML template,
        # this value is untrusted user input and has to be escaped there.
        body_lines.extend(["", "Context from the requester:", note.strip()])
    body_lines.extend(["", ask])
    if conversation_id:
        body_lines.append(f"Reference: {conversation_id}")
    body_lines.extend(["", attached, "", "— Acme Scoping Assistant"])

    attachments = (MailAttachment(filename=filename, content=content, mime=mime),)
    return MailDraft(
        contact=contact,
        subject=subject,
        body="\n".join(body_lines),
        kind=kind,
        attachments=attachments,
    )


def send_request_email(mailer: Mailer, draft: MailDraft) -> MailResult:
    return mailer.send(
        MailMessage(
            to_name=draft.contact.name,
            to_email=draft.contact.email,
            subject=draft.subject,
            body=draft.body,
            attachments=draft.attachments,
        )
    )


def _short_id(conversation_id: str | None) -> str:
    if not conversation_id:
        return "draft"
    return conversation_id.replace("-", "")[:8]
