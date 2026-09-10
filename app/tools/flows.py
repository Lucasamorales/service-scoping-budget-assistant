"""Status-driven business flows: CTAs, quote enrichment, confirm → mail."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace

from app.core.types import ServiceItem, Status
from app.orchestrator.history import HistoryTurn
from app.store.audit import (
    OUTCOME_EMAIL_DRAFTED,
    OUTCOME_EMAIL_FAILED,
    OUTCOME_EMAIL_SENT,
    AuditStore,
)
from app.store.budget import BudgetStore
from app.store.contacts import Contact, ContactDirectory
from app.store.mail import Mailer
from app.store.quote import RateCard
from app.tools.actions import Action, yes_no_actions
from app.tools.budget import answer_budget
from app.tools.mail import build_request_email, send_request_email
from app.tools.quote import QuoteOutcome, quote_for

CatalogGet = Callable[[str], ServiceItem | None]
"""Looks a service up by id. Passed in rather than importing the catalog so a
confirm can be tested without building one."""

__all__ = [
    "FlowResult",
    "PendingAction",
    "SessionIdentity",
    "confirm_pending",
    "enrich_scope_flow",
    "is_affirmative",
    "send_actions",
]

_YES_RE = re.compile(
    r"^(?:yes|yep|yeah|yup|y|sure|ok|okay|please|go ahead|do it|send it|sounds good|"
    r"affirmative|confirmed?)\b"
)
_NO_RE = re.compile(
    r"^(?:no|nope|nah|n|cancel|stop|don'?t|do not|not (?:yet|now|right now)|"
    r"never ?mind|hold off)\b"
)
_RETRACTION_RE = re.compile(r"\b(?:don'?t|do not|cancel|stop|wait|hold on|hold off)\b")
"""An affirmative followed by a retraction is treated as neither, so the
assistant asks again rather than acting on "yes, but don't send it yet"."""


_YES_LABEL = {
    "email_am": "Yes, ping my AM",
    "email_am_variable": "Yes, email my AM",
    "email_cm_po": "Yes, request a PO",
}

_ROLE_WORD = {
    "email_cm_po": "your Country Manager",
    "email_am": "your Account Manager",
    "email_am_variable": "your Account Manager",
}

_CONTEXT_PROMPT_DEFAULT = "Add some context for this request"

_CONTEXT_PROMPT = {
    "email_cm_po": "Add some context for this request",
    "email_am": "Add some context for this request",
    # A manual quote is the one where the reader has to act on the detail
    # rather than just approve it, so the ask names what they need.
    "email_am_variable": "Add some context — what do they need to know to price it?",
}

_CONTEXT_PLACEHOLDER = "e.g. New branch opening in March, we need these for the launch event"


def send_actions(kind: str) -> tuple[Action, ...]:
    """The Yes/No pair for a CTA that would send an email.

    One place decides the label, the prompt and the example, because the labels
    were previously written out at five call sites across two modules — and
    adding the context box to four of them left the fifth, the purchase order
    itself, still firing without asking.
    """
    return yes_no_actions(
        yes_label=_YES_LABEL.get(kind, "Yes, send it"),
        prompt=_CONTEXT_PROMPT.get(kind, _CONTEXT_PROMPT_DEFAULT),
        placeholder=_CONTEXT_PLACEHOLDER,
    )


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    subject: str | None = None
    role: str | None = None
    country: str | None = None
    branch: str | None = None


@dataclass(frozen=True, slots=True)
class PendingAction:
    kind: str
    """``email_am`` | ``email_cm_po`` | ``email_am_variable``."""

    service_id: str | None = None
    quote_amount: float | None = None
    currency: str = "GBP"
    recipient_country: str | None = None
    recipient_name: str | None = None
    needs_country: bool = False
    """True while we wait for the user to name their country before send."""


@dataclass(frozen=True, slots=True)
class FlowResult:
    text: str
    actions: tuple[Action, ...] = ()
    pending: PendingAction | None = None
    citations: tuple[str, ...] = ()
    skip_model: bool = True
    audit_outcome: str | None = None
    """Override audit outcome (email_sent / email_drafted / …)."""

    email: dict[str, object] | None = None
    """Optional email metadata for the audit trail."""


def is_affirmative(message: str) -> bool | None:
    """True / False for yes/no; None if neither.

    Matched on the opening words rather than the whole message, because people
    confirm in sentences — "yes please", "ok go ahead, send it to the UK AM".
    An exact-match set read those as neither, which left the user pressing Yes
    at a CTA that would not fire.
    """
    cleaned = " ".join(message.strip().lower().split()).strip(".!?,;:")
    if not cleaned:
        return None
    # Checked first: "no thanks" and "not yet" both open with a yes-shaped word
    # in some phrasings, and a refusal must never be read as consent.
    if _NO_RE.match(cleaned):
        return False
    if _YES_RE.match(cleaned):
        return None if _RETRACTION_RE.search(cleaned) else True
    return None


def enrich_scope_flow(
    item: ServiceItem,
    *,
    contacts: ContactDirectory,
    quote_store: RateCard | None,
    budget_store: BudgetStore | None,
    identity: SessionIdentity,
    question: str,
) -> FlowResult | None:
    """Return a flow overlay for resolved scope statuses that need CTAs."""
    if item.status is Status.IN_SCOPE:
        return _flow_in_scope(item, contacts, budget_store, identity, question)
    if item.status is Status.QUOTE_REQUIRED:
        return _flow_quote(item, contacts, quote_store, budget_store, identity, question)
    return None


def confirm_pending(
    message: str,
    pending: PendingAction,
    *,
    catalog_get: CatalogGet,
    contacts: ContactDirectory,
    mailer: Mailer,
    identity: SessionIdentity,
    history: tuple[HistoryTurn, ...],
    conversation_id: str | None = None,
    audit_log: AuditStore | None = None,
    note: str | None = None,
    asset_base_url: str = "",
) -> FlowResult:
    answer = is_affirmative(message)
    context = (note or "").strip()

    def send(ready: PendingAction) -> FlowResult:
        return _send_pending(
            ready,
            catalog_get=catalog_get,
            contacts=contacts,
            mailer=mailer,
            identity=identity,
            history=history,
            conversation_id=conversation_id,
            audit_log=audit_log,
            message=message,
            note=context,
            asset_base_url=asset_base_url,
        )

    if answer is False:
        return FlowResult(text="No problem — I won't send anything. Ask whenever you're ready.")

    # Waiting on country (after Yes, or user is answering the country prompt).
    if pending.needs_country:
        matched = contacts.match_country(message)
        if matched is None:
            return _ask_country(pending, contacts, again=True)
        return send(replace(pending, recipient_country=matched, needs_country=False))

    if answer is not True:
        # Free text while we still expected Yes/No. A country name is a useful
        # slot fill, but naming a country is not consent to email anyone — take
        # the detail and still ask before sending.
        matched = contacts.match_country(message)
        if matched is not None and not (pending.recipient_country or identity.country):
            pending = replace(pending, recipient_country=matched)
        return _ask_confirm(pending, contacts)

    # Affirmative Yes — need a country before we can pick the AM.
    country = pending.recipient_country or identity.country
    if not country or contacts.for_country(country) is None:
        matched = contacts.match_country(message)
        if matched is None:
            return _ask_country(pending, contacts, again=False)
        return send(replace(pending, recipient_country=matched, needs_country=False))

    # Nothing goes out without context. Enforced here as well as in the client,
    # because a rule the browser keeps is not a rule: the API is the thing that
    # sends the email, and it is reachable without the widget.
    #
    # Checked after the country, so somebody who has to answer "which country?"
    # is not also told off about a note in the same breath.
    if not context:
        return _ask_context(pending, contacts)

    return send(pending)


def _ask_context(pending: PendingAction, contacts: ContactDirectory) -> FlowResult:
    """Keep the CTA alive and ask for the context that has to travel with it."""
    contact = _recipient_for(pending, contacts)
    who = contact.name if contact else _ROLE_WORD.get(pending.kind, "them")
    return FlowResult(
        text=(
            f"Before I send this, give {who} a line of context — what it's for, "
            "and anything they need to know."
        ),
        actions=send_actions(pending.kind),
        pending=pending,
    )


def _recipient_for(pending: PendingAction, contacts: ContactDirectory) -> Contact | None:
    """Who this pending action would go to, if the country is already known."""
    role = "country_manager" if pending.kind == "email_cm_po" else "account_manager"
    return contacts.for_country(pending.recipient_country, role=role)


def _ask_confirm(pending: PendingAction, contacts: ContactDirectory) -> FlowResult:
    """Keep the CTA alive without sending anything."""
    contact = _recipient_for(pending, contacts)
    who = f" for **{contact.name}**" if contact else ""
    return FlowResult(
        text=(
            f"I still have that email ready{who}. "
            "Reply **Yes** to send it, or **No** to cancel."
        ),
        actions=send_actions(pending.kind),
        pending=pending,
    )


def _ask_country(
    pending: PendingAction,
    contacts: ContactDirectory,
    *,
    again: bool,
) -> FlowResult:
    waiting = replace(pending, needs_country=True)
    choices = contacts.selectable_countries()
    actions = tuple(
        Action(
            id=f"country_{name.lower().replace(' ', '_')}",
            label=name,
            kind="message",
            message=name,
        )
        for name in choices
    )
    if again:
        text = (
            "I still need your country so I know who to email. "
            "Pick one below, or type it (UK, France, Canada, or Australia)."
        )
    else:
        text = "Which country are you in? I’ll route this to the right person."
    return FlowResult(text=text, actions=actions, pending=waiting)


def _send_pending(
    pending: PendingAction,
    *,
    catalog_get: CatalogGet,
    contacts: ContactDirectory,
    mailer: Mailer,
    identity: SessionIdentity,
    history: tuple[HistoryTurn, ...],
    conversation_id: str | None = None,
    audit_log: AuditStore | None = None,
    message: str | None = None,
    note: str | None = None,
    asset_base_url: str = "",
) -> FlowResult:
    country = pending.recipient_country or identity.country
    role = (
        "country_manager"
        if pending.kind == "email_cm_po"
        else "account_manager"
    )
    contact = contacts.for_country(country, role=role)
    if contact is None:
        return _ask_country(pending, contacts, again=True)

    item = catalog_get(pending.service_id) if pending.service_id else None
    draft = build_request_email(
        kind=pending.kind,
        contact=contact,
        item=item,
        requester=identity.subject,
        country=country,
        branch=identity.branch,
        quote_amount=pending.quote_amount,
        currency=pending.currency,
        history=history,
        conversation_id=conversation_id,
        audit_log=audit_log,
        role=identity.role,
        current_message=message,
        note=note,
        asset_base_url=asset_base_url,
        from_address=mailer.from_address,
    )
    result = send_request_email(mailer, draft)
    attached = draft.attachments[0].filename if draft.attachments else None
    email_meta: dict[str, object] = {
        "kind": pending.kind,
        "to": contact.email,
        "to_name": contact.name,
        "subject": draft.subject,
        "provider_id": result.provider_id,
        "detail": result.detail,
        "attachment": attached,
        "note": note or None,
    }
    if result.sent:
        extra = f" Full conversation attached ({attached})." if attached else ""
        return FlowResult(
            text=(
                f"Sent to **{contact.name}** ({contact.email}). "
                f"Subject: {draft.subject}.{extra}"
            ),
            audit_outcome=OUTCOME_EMAIL_SENT,
            email=email_meta,
        )
    if result.attempted:
        # A provider was called and refused. Recording this as a draft hid real
        # delivery failures behind the same audit outcome as "no mail here".
        return FlowResult(
            text=(
                f"I couldn't send this to **{contact.name}** ({contact.email}) — "
                f"{result.detail} Nothing has gone out, so it is worth trying again "
                "or telling them directly."
            ),
            audit_outcome=OUTCOME_EMAIL_FAILED,
            email=email_meta,
        )

    attach_note = (
        f" A PDF of the conversation would be attached ({attached})."
        if attached
        else ""
    )
    return FlowResult(
        text=(
            f"I'd send this to **{contact.name}** ({contact.email}), but mail isn't connected "
            f"here yet ({result.detail}). Here's the draft:{attach_note}\n\n"
            f"**Subject:** {draft.subject}\n\n{draft.body}"
        ),
        audit_outcome=OUTCOME_EMAIL_DRAFTED,
        email=email_meta,
    )


def _flow_in_scope(
    item: ServiceItem,
    contacts: ContactDirectory,
    budget_store: BudgetStore | None,
    identity: SessionIdentity,
    question: str,
) -> FlowResult:
    parts = [
        f"Yes — **{item.display_name}** is included in our scope (free of charge).",
        item.status_meaning,
    ]
    citations: list[str] = []
    if budget_store is not None and (identity.branch or question):
        budget = answer_budget(question, budget_store, session_branch=identity.branch)
        if budget.snapshot is not None and budget.snapshot.remaining is not None:
            parts.append(
                f"For awareness, **{budget.snapshot.branch.name}** has "
                f"**{budget.snapshot.remaining:,.2f}** left in **{budget.snapshot.month}**."
            )
            citations.append(budget.snapshot.citation)

    contact = contacts.for_country(identity.country, role="account_manager")
    if contact is None:
        parts.append(
            "Would you like me to ping your Account Manager with this request? "
            "If I don’t already know your country, I’ll ask next."
        )
    else:
        parts.append(f"Would you like me to ping **{contact.name}** with this request?")

    pending = PendingAction(
        kind="email_am",
        service_id=item.item_id,
        recipient_country=identity.country,
        recipient_name=contact.name if contact else None,
    )
    return FlowResult(
        text="\n\n".join(parts),
        actions=send_actions("email_am"),
        pending=pending,
        citations=tuple(citations),
    )


def _flow_quote(
    item: ServiceItem,
    contacts: ContactDirectory,
    quote_store: RateCard | None,
    budget_store: BudgetStore | None,
    identity: SessionIdentity,
    question: str,
) -> FlowResult:
    outcome: QuoteOutcome = quote_for(
        item,
        quote_store,
        budget_store,
        session_branch=identity.branch,
        question=question,
    )
    citations: list[str] = []
    if outcome.budget is not None:
        citations.append(outcome.budget.citation)

    if outcome.kind == "variable" or outcome.kind == "missing":
        contact = contacts.for_country(identity.country, role="account_manager")
        pending = PendingAction(
            kind="email_am_variable",
            service_id=item.item_id,
            recipient_country=identity.country,
            recipient_name=contact.name if contact else None,
        )
        return FlowResult(
            text=outcome.text,
            actions=send_actions("email_am_variable"),
            pending=pending,
            citations=tuple(citations),
        )

    contact = contacts.for_country(identity.country, role="country_manager")
    pending = PendingAction(
        kind="email_cm_po",
        service_id=item.item_id,
        quote_amount=outcome.price,
        currency=outcome.currency,
        recipient_country=identity.country,
        recipient_name=contact.name if contact else None,
    )
    return FlowResult(
        text=outcome.text,
        actions=send_actions("email_cm_po"),
        pending=pending,
        citations=tuple(citations),
    )
