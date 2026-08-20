"""Running the lookups a plan asked for.

One capability per method, each one deterministic, each one writing into the
:class:`~app.orchestrator.facts.FactPack`. Several may run for a single turn,
which is the point: "do we have budget for a photoshoot in Basingstoke" needs a
price and a ledger, and answering half of it was the old design's defining
limitation.

Nothing here consults a model. A capability that finds nothing simply does not
record itself as satisfied, and an empty pack becomes a clarifying question
downstream — so a bad plan degrades into a question rather than into a
confident answer about the wrong thing.

The deterministic wording is assembled here too, as ``fallback_text``. It is
what the user sees when the model is off or misbehaves, and it is what the
existing behaviour tests assert, so the two paths cannot drift apart unnoticed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import structlog

from app.core.types import ServiceItem, Status
from app.knowledge.catalog import ServiceCatalog
from app.knowledge.retriever import RetrievalResult
from app.orchestrator.facts import FactPack
from app.orchestrator.history import HistoryTurn
from app.orchestrator.plan import Capability, Plan
from app.orchestrator.resolver import Outcome, Resolution, ScopeResolver
from app.orchestrator.router import ConversationState, Route
from app.store.audit import AuditStore
from app.store.budget import BudgetStore
from app.store.contacts import (
    ROLE_ACCOUNT_MANAGER,
    ROLE_COUNTRY_MANAGER,
    Contact,
    ContactDirectory,
)
from app.store.mail import Mailer
from app.store.quote import QuoteStore
from app.store.roster import RosterStore
from app.tools.actions import yes_no_actions
from app.tools.budget import answer_budget
from app.tools.catalog import list_services
from app.tools.flows import (
    FlowResult,
    PendingAction,
    SessionIdentity,
    confirm_pending,
    enrich_scope_flow,
)
from app.tools.quote import QuoteOutcome, quote_for

__all__ = ["Executor"]

logger = structlog.get_logger(__name__)

_ROLE_WORDS = {
    ROLE_ACCOUNT_MANAGER: ("account manager", " am ", "my am", "our am"),
    ROLE_COUNTRY_MANAGER: ("country manager", " cm ", "my cm", "our cm"),
}

_CLARIFY = (
    "I couldn't tell which service or site you mean. Name the request (like merch or "
    "a photoshoot) or a branch, and I'll tell you whether it's covered, what it costs, "
    "or what's left in the budget."
)

_GREETING = (
    "Hey — ask me about a marketing request and I'll tell you if it's in scope, local, "
    "out of scope, or needs a quote. I can also check what's left in a branch's budget."
)

_ACKNOWLEDGED = "No problem. Anything else you need checking?"


@dataclass(frozen=True, slots=True)
class Executor:
    """Holds the stores, and runs a plan against them."""

    catalog: ServiceCatalog
    resolver: ScopeResolver
    contacts: ContactDirectory
    budget_store: BudgetStore | None = None
    quote_store: QuoteStore | None = None
    roster: RosterStore | None = None
    audit_log: AuditStore | None = None

    def run(
        self,
        question: str,
        plan: Plan,
        route: Route,
        state: ConversationState,
        identity: SessionIdentity,
        history: tuple[HistoryTurn, ...] = (),
        *,
        resolution: Resolution | None = None,
        retrieval: RetrievalResult | None = None,
        confirm: PendingAction | None = None,
        mailer: Mailer | None = None,
        conversation_id: str | None = None,
    ) -> FactPack:
        pack = FactPack(plan=plan)

        if plan.wants(Capability.HANDOVER) and route.handover_topic is not None:
            return replace(
                pack,
                handover=route.handover_topic,
                satisfied=(Capability.HANDOVER,),
                fallback_text=route.handover_topic.reason,
            )

        if plan.wants(Capability.MAIL) and confirm is not None and mailer is not None:
            pack = self._mail(
                pack, question, confirm, identity, history, mailer, conversation_id
            )

        if plan.needs_a_service:
            pack = self._scope(
                pack, question, plan, route, identity, resolution, retrieval
            )

        if plan.wants(Capability.BUDGET):
            pack = self._budget(pack, question, plan, state, identity)

        if plan.wants(Capability.LIST):
            pack = self._list(pack, question, plan)

        if plan.wants(Capability.CAPABILITIES):
            pack = self._capabilities(pack)

        if plan.wants(Capability.ROSTER):
            pack = self._roster(pack, question, plan, identity)

        if plan.wants(Capability.GREETING) and not pack.satisfied:
            pack = replace(
                pack,
                satisfied=(Capability.GREETING,),
                fallback_text=_ACKNOWLEDGED if _is_thanks(question) else _GREETING,
            )

        if pack.is_empty:
            pack = replace(
                pack,
                satisfied=(Capability.CLARIFY,),
                fallback_text=pack.fallback_text or _CLARIFY,
            )

        logger.info(
            "executor.ran",
            planned=[capability.value for capability in plan.capabilities],
            satisfied=[capability.value for capability in pack.satisfied],
            verdict=pack.verdict.value if pack.verdict else None,
        )
        return pack

    # -- capabilities ----------------------------------------------------

    def _scope(
        self,
        pack: FactPack,
        question: str,
        plan: Plan,
        route: Route,
        identity: SessionIdentity,
        resolution: Resolution | None,
        retrieval: RetrievalResult | None,
    ) -> FactPack:
        resolution = resolution or self.resolve(question, plan, route)
        pack = replace(pack, scope=resolution)

        if retrieval is not None:
            pack = replace(
                pack,
                evidence=tuple(hit.chunk for hit in retrieval.hits),
                citations=tuple(
                    hit.chunk.section_title or hit.chunk.source for hit in retrieval.hits
                ),
            )

        if resolution.outcome is Outcome.AMBIGUOUS:
            question_text = resolution.question()
            return replace(
                pack,
                satisfied=(*pack.satisfied, Capability.SCOPE),
                fallback_text=_join(pack.fallback_text, question_text or _CLARIFY),
            )

        if not resolution.decided:
            # Nothing named. Not satisfied, so the turn falls through to a
            # clarifying question instead of an answer about a near-miss.
            return pack

        item = resolution.candidates[0].item
        effective = SessionIdentity(
            subject=identity.subject,
            role=identity.role,
            country=identity.country,
            branch=identity.branch or plan.slots.branch or route.branch,
        )
        satisfied = (*pack.satisfied, Capability.SCOPE)

        if item.status is Status.QUOTE_REQUIRED:
            outcome = quote_for(
                item,
                self.quote_store,
                self.budget_store if plan.wants(Capability.BUDGET) else None,
                session_branch=effective.branch,
                question=question if plan.wants(Capability.BUDGET) else "",
            )
            flow = self._quote_flow(item, outcome, effective)
            pack = replace(
                pack,
                quote=outcome,
                satisfied=(*satisfied, Capability.QUOTE)
                if Capability.QUOTE not in satisfied
                else satisfied,
            )
            return self._apply_flow(pack, flow)

        if item.status is Status.IN_SCOPE:
            flow = enrich_scope_flow(
                item,
                contacts=self.contacts,
                quote_store=self.quote_store,
                budget_store=self.budget_store if plan.wants(Capability.BUDGET) else None,
                identity=effective,
                question=question if plan.wants(Capability.BUDGET) else "",
            )
            pack = replace(pack, satisfied=satisfied)
            return self._apply_flow(pack, flow) if flow is not None else pack

        # Local / out of scope: a verdict and a reason, no CTA to offer.
        meaning = resolution.status_meaning or ""
        return replace(
            pack,
            satisfied=satisfied,
            fallback_text=_join(
                pack.fallback_text, f"**{item.display_name}** — {meaning}".strip()
            ),
        )

    def _quote_flow(
        self,
        item: ServiceItem,
        outcome: QuoteOutcome,
        identity: SessionIdentity,
    ) -> FlowResult:
        if outcome.kind in {"variable", "missing"}:
            contact = self.contacts.for_country(identity.country, role=ROLE_ACCOUNT_MANAGER)
            return FlowResult(
                text=outcome.text,
                actions=yes_no_actions(yes_label="Yes, email my AM"),
                pending=PendingAction(
                    kind="email_am_variable",
                    service_id=item.item_id,
                    recipient_country=identity.country,
                    recipient_name=contact.name if contact else None,
                ),
            )
        contact = self.contacts.for_country(identity.country, role=ROLE_COUNTRY_MANAGER)
        return FlowResult(
            text=outcome.text,
            actions=yes_no_actions(yes_label="Yes, request a PO"),
            pending=PendingAction(
                kind="email_cm_po",
                service_id=item.item_id,
                quote_amount=outcome.price,
                currency=outcome.currency,
                recipient_country=identity.country,
                recipient_name=contact.name if contact else None,
            ),
            citations=(outcome.budget.citation,) if outcome.budget else (),
        )

    def _budget(
        self,
        pack: FactPack,
        question: str,
        plan: Plan,
        state: ConversationState,
        identity: SessionIdentity,
    ) -> FactPack:
        # A quote already attached its own budget line for the same site.
        if pack.quote is not None and pack.quote.budget is not None:
            return pack.with_satisfied(Capability.BUDGET)

        result = answer_budget(
            question,
            self.budget_store,
            session_branch=plan.slots.branch or identity.branch,
            session_country=plan.slots.country or identity.country,
            sticky_country=state.budget_country,
            sticky_branch=state.budget_branch,
            sticky_month=plan.slots.month or state.budget_month,
        )
        return replace(
            pack,
            budget=result,
            satisfied=(*pack.satisfied, Capability.BUDGET),
            citations=pack.citations + result.citations,
            fallback_text=_join(pack.fallback_text, result.text),
        )

    def _list(self, pack: FactPack, question: str, plan: Plan) -> FactPack:
        listing = list_services(
            self.catalog,
            question,
            section=plan.slots.section,
            status=plan.slots.status,
        )
        return replace(
            pack,
            listing=listing,
            satisfied=(*pack.satisfied, Capability.LIST),
            fallback_text=_join(pack.fallback_text, listing),
        )

    def _capabilities(self, pack: FactPack) -> FactPack:
        sections = ", ".join(sorted(self.catalog.sections()))
        counts = {status: 0 for status in Status}
        for item in self.catalog:
            counts[item.status] += 1
        summary = (
            "I can tell you whether a request is covered by central marketing, sits with "
            "your local team, is out of scope, or needs quoting first — the verdict comes "
            "from Acme's own service breakdown, not from guesswork. I can price the "
            "chargeable ones from the rate card, check what's left of a branch's budget "
            "for the fiscal month, list what we cover, and email your Account or Country "
            "Manager once you say the word.\n\n"
            f"The catalog runs to {sum(counts.values())} services across: {sections}. "
            f"{counts[Status.IN_SCOPE]} are included, "
            f"{counts[Status.QUOTE_REQUIRED]} are on demand, "
            f"{counts[Status.LOCAL]} sit with local teams and "
            f"{counts[Status.OUT_OF_SCOPE]} are out of scope."
        )
        return replace(
            pack,
            capability_summary=summary,
            satisfied=(*pack.satisfied, Capability.CAPABILITIES),
            fallback_text=_join(pack.fallback_text, summary),
        )

    def _roster(
        self,
        pack: FactPack,
        question: str,
        plan: Plan,
        identity: SessionIdentity,
    ) -> FactPack:
        country = plan.slots.country or identity.country
        role = _role_wanted(question)
        found: list[Contact] = []
        if country:
            for wanted in (role,) if role else (ROLE_ACCOUNT_MANAGER, ROLE_COUNTRY_MANAGER):
                contact = self.contacts.for_country(country, role=wanted)
                if contact is not None and contact not in found:
                    found.append(contact)

        if found:
            lines = [
                f"Your {contact.role.replace('_', ' ')} for {country} is "
                f"**{contact.name}** ({contact.email})."
                for contact in found
            ]
            return replace(
                pack,
                roster=tuple(found),
                satisfied=(*pack.satisfied, Capability.ROSTER),
                fallback_text=_join(pack.fallback_text, "\n".join(lines)),
            )

        countries = ", ".join(self.contacts.selectable_countries())
        note = (
            "I need to know which country you're in before I can name the right person"
            + (f" — I have contacts for {countries}." if countries else ".")
        )
        return replace(
            pack,
            roster_note=note,
            satisfied=(*pack.satisfied, Capability.ROSTER),
            fallback_text=_join(pack.fallback_text, note),
        )

    def _mail(
        self,
        pack: FactPack,
        question: str,
        pending: PendingAction,
        identity: SessionIdentity,
        history: tuple[HistoryTurn, ...],
        mailer: Mailer,
        conversation_id: str | None,
    ) -> FactPack:
        flow = confirm_pending(
            question,
            pending,
            catalog_get=self.catalog.get,
            contacts=self.contacts,
            mailer=mailer,
            identity=identity,
            history=history,
            conversation_id=conversation_id,
            audit_log=self.audit_log,
        )
        return self._apply_flow(pack.with_satisfied(Capability.MAIL), flow)

    # -- plumbing --------------------------------------------------------

    def _apply_flow(self, pack: FactPack, flow: FlowResult) -> FactPack:
        return replace(
            pack,
            actions=flow.actions or pack.actions,
            pending=flow.pending or pack.pending,
            audit_outcome=flow.audit_outcome or pack.audit_outcome,
            email=flow.email or pack.email,
            citations=pack.citations + flow.citations,
            fallback_text=_join(pack.fallback_text, flow.text),
        )

    def resolve(self, question: str, plan: Plan, route: Route) -> Resolution:
        """Which service the turn is about, from the planner's phrase."""
        if route.selected_item_id and (item := self.catalog.get(route.selected_item_id)):
            return self.resolver.resolve(item.display_name)

        phrase = plan.slots.service_phrase or question
        resolution = self.resolver.resolve(phrase)
        if resolution.outcome is not Outcome.UNKNOWN:
            return resolution

        # A planner phrase can be narrower than the message; try the message
        # before giving up, then anything carried from the previous turn.
        if phrase != question:
            resolution = self.resolver.resolve(question)
            if resolution.outcome is not Outcome.UNKNOWN:
                return resolution

        if route.carried_item_ids:
            previous = self.catalog.get(route.carried_item_ids[0])
            if previous is not None:
                carried = self.resolver.resolve(f"{previous.display_name} {question}")
                if carried.outcome is not Outcome.UNKNOWN:
                    return carried
        return resolution


def _role_wanted(question: str) -> str | None:
    padded = f" {question.lower()} "
    for role, words in _ROLE_WORDS.items():
        if any(word in padded for word in words):
            return role
    return None


def _is_thanks(message: str) -> bool:
    return any(
        word in message.lower() for word in ("thanks", "thank you", "cheers", "ta ", "great")
    )


def _join(existing: str, addition: str) -> str:
    if not addition:
        return existing
    if not existing:
        return addition
    return f"{existing}\n\n{addition}"
