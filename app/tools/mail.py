"""Build and send request emails after an explicit Yes in chat.

The body is a short résumé the Account or Country Manager can act on, rendered
from the designed templates in ``app/assets/templates`` — HTML and plain text
from the same set of values, so the two cannot say different things. The full
thread travels as a PDF attachment (plain text if PDF generation fails), built
from the audit log rather than the clipped browser history.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.money import format_money
from app.core.types import ServiceItem
from app.orchestrator.history import HistoryTurn
from app.store.audit import AuditStore
from app.store.contacts import Contact
from app.store.mail import MailAttachment, Mailer, MailMessage, MailResult
from app.tools.email_template import render_html, render_text, subject_for
from app.tools.transcript import build_transcript, transcript_attachment

__all__ = ["MailDraft", "build_request_email", "send_request_email"]

_PREHEADER_LEAD = {
    "email_am": "In scope, free of charge",
    "email_cm_po": "{amount} purchase order",
    "email_am_variable": "Manual quote needed",
}

_PREHEADER_CAP = 90
"""Past this an inbox truncates it anyway, and the requester's name is the
first thing worth losing — everything before it has already said what the mail
is."""

_ROLE_LABEL = {
    "am": "Account Manager",
    "gm": "General Manager",
    "country": "Country Manager",
    "admin": "Admin",
}
"""How the requester's own role is written out.

Sign-in stores it as a wire code, and "Remy, am" in front of a country manager
is the same failure as the "Y" the status row used to print — the system's
vocabulary, in an email to somebody who has never seen it. An unrecognised
value is dropped rather than guessed at."""

_UNKNOWN = "Not recorded"
"""What a value nobody supplied is called.

Not "unknown" in lower case, which reads as though the system had looked and
failed. Nobody typed it: the sign-in leaves the venue optional.
"""

_STATUS_LABEL = {
    "in_scope": "In scope",
    "quote_required": "Quote required",
    "local": "Local",
    "out_of_scope": "Out of scope",
}
"""How a verdict is named to the person receiving the mail.

The documents carry two other forms and neither can go in front of a country
manager. ``status_raw`` is the spreadsheet's own code — for two of the four
verdicts that is the single letter ``Y`` or ``N``. ``status_meaning`` is the
corpus's internal gloss, and the in-scope one does not parse: "We can do it and
is within our scope".

These are the same four words the chat window puts on its verdict pill, so a
request reads the same wherever somebody meets it.
"""


@dataclass(frozen=True, slots=True)
class MailDraft:
    contact: Contact
    subject: str
    body: str
    kind: str
    html: str = ""
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
    asset_base_url: str = "",
    from_address: str = "",
) -> MailDraft:
    service = item.display_name if item else "a marketing request"
    values = _values(
        kind=kind,
        contact=contact,
        item=item,
        service=service,
        requester=requester,
        country=country,
        branch=branch,
        quote_amount=quote_amount,
        currency=currency,
        note=note,
        conversation_id=conversation_id,
        role=role,
        asset_base_url=asset_base_url,
        from_address=from_address,
    )
    subject = subject_for(kind, values) or f"Acme request: {service}"
    values["subject"] = subject
    values["preheader"] = _preheader(kind, values)

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
        # The written-out role, not the sign-in code — the PDF puts it on the
        # cover, where "Remy, am" reads exactly as badly as it does in the mail.
        role=values["requester_role"],
        country=country,
        branch=branch,
        service=service,
        item=item,
        recipient=contact.name,
        amount=values.get("amount", ""),
        note=note,
        kind=kind,
        conversation_id=conversation_id,
    )
    values["attachment_filename"] = filename

    return MailDraft(
        contact=contact,
        subject=subject,
        body=render_text(kind, values),
        html=render_html(kind, values),
        kind=kind,
        attachments=(MailAttachment(filename=filename, content=content, mime=mime),),
    )


def _values(
    *,
    kind: str,
    contact: Contact,
    item: ServiceItem | None,
    service: str,
    requester: str | None,
    country: str | None,
    branch: str | None,
    quote_amount: float | None,
    currency: str,
    note: str | None,
    conversation_id: str | None,
    role: str | None,
    asset_base_url: str,
    from_address: str,
) -> dict[str, str]:
    base = asset_base_url.rstrip("/")
    job = _ROLE_LABEL.get((role or "").strip().casefold(), "")
    values = {
        "recipient_name": contact.name,
        "requester_name": requester or _UNKNOWN,
        "requester_role": job,
        "country": country or _UNKNOWN,
        # Falls back to the country so the subject still says where this came
        # from. A subject reading "· Not recorded" tells nobody anything.
        "branch": branch or country or _UNKNOWN,
        "service": service,
        # Split, because the design sets the item as the headline and the
        # section as the line beneath it. display_name joins the two for the
        # details table, where one line is what is wanted.
        "service_name": item.item if item else service,
        "service_category": item.section if item else "",
        "status_label": _STATUS_LABEL.get(item.status.value, "") if item else "",
        "status_raw": item.status_raw.strip() if item else "",
        "status_meaning": item.status_meaning if item else "",
        # The venue as a person would say it, rather than two fields joined by
        # a comma whatever they happen to hold. Without this an unset branch
        # printed "unknown, United Kingdom".
        "venue_line": ", ".join(part for part in (branch, country) if part) or _UNKNOWN,
        "requester_line": _requested_by(requester, job, None),
        "requested_by": _requested_by(requester, job, branch or country),
        "context": (note or "").strip(),
        "reference": conversation_id or _UNKNOWN,
        "from_address": from_address,
        # Absolute or nothing: an email has no origin to resolve a relative
        # path against. Both are optional by design — the templates carry the
        # whole hierarchy in text, so a stripped stylesheet or a blocked image
        # costs the reader nothing.
        "asset_base": base,
        "logo_url": f"{base}/widget/assets/acme-logo-email.png" if base else "",
        "font_css_url": f"{base}/widget/assets/email-fonts.css" if base else "",
    }
    if quote_amount is not None:
        values["amount"] = format_money(quote_amount, currency)
    return values


def _requested_by(requester: str | None, role: str | None, where: str | None) -> str:
    """"Alex Fenn, Marketing Executive at Acme Basingstoke", minus whatever is
    missing — never "at unknown"."""
    who = ", ".join(part for part in (requester, role) if part) or _UNKNOWN
    return f"{who} at {where}" if where else who


def _preheader(kind: str, values: dict[str, str]) -> str:
    """The hidden line an inbox shows between the subject and the open."""
    lead = _PREHEADER_LEAD.get(kind, "").format(amount=values.get("amount", ""))
    parts = [
        lead,
        values.get("service") or values.get("service_name", ""),
        values.get("branch", ""),
        f"asked for by {values['requester_name']}" if values.get("requester_name") else "",
    ]
    full = " · ".join(part for part in parts if part)
    if len(full) <= _PREHEADER_CAP:
        return full
    return " · ".join(part for part in parts[:-1] if part)


def send_request_email(mailer: Mailer, draft: MailDraft) -> MailResult:
    return mailer.send(
        MailMessage(
            to_name=draft.contact.name,
            to_email=draft.contact.email,
            subject=draft.subject,
            body=draft.body,
            html=draft.html,
            attachments=draft.attachments,
        )
    )


def _short_id(conversation_id: str | None) -> str:
    if not conversation_id:
        return "draft"
    return conversation_id.replace("-", "")[:8]
