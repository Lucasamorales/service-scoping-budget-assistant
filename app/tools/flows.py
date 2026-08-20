"""Status-driven business flows: CTAs, quote enrichment, confirm → mail."""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.core.types import ServiceItem, Status
from app.orchestrator.history import HistoryTurn
from app.store.audit import AuditStore
from app.store.budget import BudgetStore
from app.store.contacts import ContactDirectory
from app.store.mail import Mailer
from app.store.quote import QuoteStore
from app.tools.actions import Action, yes_no_actions
from app.tools.budget import answer_budget
from app.tools.mail import build_request_email, send_request_email
from app.tools.quote import QuoteOutcome, quote_for

__all__ = [
    "FlowResult",
    "PendingAction",
    "SessionIdentity",
    "confirm_pending",
    "enrich_scope_flow",
    "is_affirmative",
]

_YES = frozenset({"yes", "y", "yep", "yeah", "sure", "please", "ok", "okay", "do it", "send it"})
_NO = frozenset({"no", "n", "nope", "nah", "no thanks", "cancel"})


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
    """True / False for yes/no; None if neither."""
    cleaned = message.strip().lower().rstrip(".!?")
    if cleaned in _YES:
        return True
    if cleaned in _NO:
        return False
    return None


def enrich_scope_flow(
    item: ServiceItem,
    *,
    contacts: ContactDirectory,
    quote_store: QuoteStore | None,
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
    catalog_get,
    contacts: ContactDirectory,
    mailer: Mailer,
    identity: SessionIdentity,
    history: tuple[HistoryTurn, ...],
    conversation_id: str | None = None,
    audit_log: AuditStore | None = None,
) -> FlowResult:
    answer = is_affirmative(message)

    if answer is False:
        return FlowResult(text="No problem — I won't send anything. Ask whenever you're ready.")

    # Waiting on country (after Yes, or user is answering the country prompt).
    if pending.needs_country:
        matched = contacts.match_country(message)
        if matched is None:
            return _ask_country(pending, contacts, again=True)
        pending = replace(pending, recipient_country=matched, needs_country=False)
        return _send_pending(
            pending,
            catalog_get=catalog_get,
            contacts=contacts,
            mailer=mailer,
            identity=identity,
            history=history,
            conversation_id=conversation_id,
            audit_log=audit_log,
        )

    if answer is not True:
        # Free text while we still expected Yes/No — keep the CTA alive.
        matched = contacts.match_country(message)
        if matched is not None and not (pending.recipient_country or identity.country):
            pending = replace(pending, recipient_country=matched)
            return _send_pending(
                pending,
                catalog_get=catalog_get,
                contacts=contacts,
                mailer=mailer,
                identity=identity,
                history=history,
                conversation_id=conversation_id,
                audit_log=audit_log,
            )
        return FlowResult(
            text="I still have that email ready. Reply **Yes** to send it, or **No** to cancel.",
            actions=yes_no_actions(yes_label="Yes, send it"),
            pending=pending,
        )

    # Affirmative Yes — need a country before we can pick the AM.
    country = pending.recipient_country or identity.country
    if not country or contacts.for_country(country) is None:
        matched = contacts.match_country(message)
        if matched is not None:
            pending = replace(pending, recipient_country=matched, needs_country=False)
            return _send_pending(
                pending,
                catalog_get=catalog_get,
                contacts=contacts,
                mailer=mailer,
                identity=identity,
                history=history,
                conversation_id=conversation_id,
                audit_log=audit_log,
            )
        return _ask_country(pending, contacts, again=False)

    return _send_pending(
        pending,
        catalog_get=catalog_get,
        contacts=contacts,
        mailer=mailer,
        identity=identity,
        history=history,
        conversation_id=conversation_id,
        audit_log=audit_log,
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
    catalog_get,
    contacts: ContactDirectory,
    mailer: Mailer,
    identity: SessionIdentity,
    history: tuple[HistoryTurn, ...],
    conversation_id: str | None = None,
    audit_log: AuditStore | None = None,
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
    }
    if result.sent:
        extra = f" Full conversation attached ({attached})." if attached else ""
        return FlowResult(
            text=(
                f"Sent to **{contact.name}** ({contact.email}). "
                f"Subject: {draft.subject}.{extra}"
            ),
            audit_outcome="email_sent",
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
        audit_outcome="email_drafted",
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
        if budget.snapshot is not None:
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
        actions=yes_no_actions(yes_label="Yes, ping my AM"),
        pending=pending,
        citations=tuple(citations),
    )


def _flow_quote(
    item: ServiceItem,
    contacts: ContactDirectory,
    quote_store: QuoteStore | None,
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
            actions=yes_no_actions(yes_label="Yes, email my AM"),
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
        actions=yes_no_actions(yes_label="Yes, request a PO"),
        pending=pending,
        citations=tuple(citations),
    )
