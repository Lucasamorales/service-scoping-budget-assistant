"""One turn, start to finish: plan, execute, compose.

    message
      → safety gates          handover topics and pending Yes/No, by rule
      → plan                  which lookups this needs (model, or the router)
      → execute               the tools, deterministically, possibly several
      → compose               the model words the facts it was given
      → guard                 anything unsupported falls back to the facts

The order is the design. Nothing that affects correctness happens after the
tools have run: verdicts are lookups, prices come from the rate card, budgets
come from the tracker, and the model's only job is the sentence. A bad plan
therefore costs a clarifying question rather than a confident wrong answer,
because an empty fact pack has nothing to assert.

The model is optional at both ends. With no planner the router still routes;
with no composer the facts still read as English. Neither absence changes a
verdict, and the reply says when it happened.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import structlog

from app.core.config import Settings, get_settings
from app.core.types import Status
from app.knowledge.catalog import ServiceCatalog, load_catalog
from app.knowledge.embeddings import Embedder, build_embedder
from app.knowledge.index import IndexContractError, KnowledgeIndex
from app.knowledge.manifest import Manifest
from app.knowledge.retriever import InMemoryRetriever, RetrievalResult
from app.orchestrator.context import load_system_prompt
from app.orchestrator.executor import Executor
from app.orchestrator.facts import FactPack
from app.orchestrator.history import HistoryTurn
from app.orchestrator.intent_semantics import InventoryIntentDetector
from app.orchestrator.llm import DETERMINISTIC, LanguageModel, build_model
from app.orchestrator.plan import Capability, Plan
from app.orchestrator.planner import ModelPlanner, Planner, build_planner
from app.orchestrator.resolver import Outcome, Resolution, ScopeResolver
from app.orchestrator.router import ConversationState, Route, Router
from app.orchestrator.wording import Worded, stream_wording, word_answer
from app.store.audit import (
    OUTCOME_CHAT_ONLY,
    OUTCOME_EMAIL_PENDING,
    AuditEvent,
    AuditStore,
    build_audit_store,
    new_conversation_id,
)
from app.store.budget import BudgetStore, build_budget_store
from app.store.contacts import ContactDirectory, load_contacts
from app.store.mail import Mailer, build_mailer
from app.store.quote import QuoteStore, load_quote_store
from app.store.roster import RosterStore, load_roster
from app.tools.actions import Action
from app.tools.budget import BudgetToolResult
from app.tools.flows import PendingAction, SessionIdentity

__all__ = ["Answer", "Pipeline", "StreamEnd", "StreamStart", "TextPiece"]

logger = structlog.get_logger(__name__)

EVIDENCE_LIMIT = 4

NO_CITATIONS = ("Searched the corpus; nothing matched closely enough to cite.",)
"""Even "nothing was retrieved" is a citation: the alternative is an answer
whose basis nobody can check."""

CATALOG_CITATION = ("Answered from the service catalog, not from retrieved prose.",)
"""For turns answered from structured data rather than from prose.

Listing the catalogue does not search it, and saying "no supporting documents"
about an answer read straight out of the registry describes a failure that did
not happen. During review that line was read as a hallucination risk on an
answer which was, in fact, the best-grounded kind this system produces."""


@dataclass(frozen=True, slots=True)
class StreamStart:
    """Everything known before generation begins - which is everything that
    matters.

    The verdict is a lookup, so it is settled the moment the request is
    understood. Emitting it first lets a client render the decision while the
    prose is still being written, and means a dropped connection mid-answer
    still delivered the part that carries the consequences.
    """

    route: Route
    resolution: Resolution
    citations: tuple[str, ...]
    notes: tuple[str, ...]
    next_state: ConversationState
    actions: tuple[Action, ...] = ()

    @property
    def awaiting_answer(self) -> bool:
        return self.resolution.outcome is Outcome.AMBIGUOUS


@dataclass(frozen=True, slots=True)
class TextPiece:
    """A fragment of the answer, as it is produced."""

    text: str


@dataclass(frozen=True, slots=True)
class StreamEnd:
    """The last event of a stream: how it went, and what it added up to."""

    text: str
    source: str
    degraded: bool = False
    truncated: bool = False
    """The model failed *after* emitting text. Nothing can be retracted at that
    point, so the caller keeps what arrived and tells the user it is partial."""


@dataclass(frozen=True, slots=True)
class Answer:
    """A completed turn: what to say, what it rests on, and where to go next."""

    text: str
    route: Route
    resolution: Resolution
    citations: tuple[str, ...]
    source: str
    """``deterministic`` or the model name. Says which path produced the text."""

    degraded: bool = False
    """The model was meant to answer and could not. Worth surfacing, so an
    outage looks like an outage rather than a change of tone."""

    notes: tuple[str, ...] = field(default=())
    next_state: ConversationState = field(default_factory=ConversationState)
    actions: tuple[Action, ...] = ()

    plan: Plan | None = None
    """Which lookups this turn asked for, and who decided. ``None`` only for
    answers built directly in tests."""

    satisfied: tuple[Capability, ...] = ()
    """Which of them actually produced facts. A planned lookup that found
    nothing is absent here, which is the difference between an answer and a
    question."""

    tokens: int = 0
    """What this turn cost, planning and wording together.

    A turn calls the model twice, and the interesting question is always "what
    did this question cost", never "what did the composer cost" — so the two
    are summed here rather than left for whoever reads the logs to join.
    Zero when neither call happened, which is every turn on the rules path.
    """

    @property
    def status(self) -> Status | None:
        return self.resolution.status

    @property
    def needs_a_human(self) -> bool:
        return self.route.needs_a_human

    @property
    def awaiting_answer(self) -> bool:
        """Whether the assistant has asked the user something and is waiting."""
        return self.resolution.outcome is Outcome.AMBIGUOUS

    def explain(self) -> str:
        plan = f"{self.plan.explain()} | " if self.plan is not None else ""
        return (
            f"{plan}{self.route.explain()} | {self.resolution.explain()} | "
            f"answered by {self.source}"
        )


class Pipeline:
    """Holds the loaded corpus and index, and runs turns against them."""

    def __init__(
        self,
        catalog: ServiceCatalog,
        index: KnowledgeIndex,
        *,
        model: LanguageModel | None = None,
        embedder: Embedder | None = None,
        system_prompt: str | None = None,
        branches: tuple[str, ...] = (),
        budget_store: BudgetStore | None = None,
        quote_store: QuoteStore | None = None,
        contacts: ContactDirectory | None = None,
        roster: RosterStore | None = None,
        mailer: Mailer | None = None,
        audit_log: AuditStore | None = None,
        use_semantic_inventory: bool = False,
        use_llm_planner: bool = True,
        use_llm_composer: bool = True,
    ) -> None:
        self.catalog = catalog
        self.index = index
        self.retriever = InMemoryRetriever(index)
        self.resolver = ScopeResolver(catalog, self.retriever, embedder)
        inventory_detector = (
            InventoryIntentDetector(embedder)
            if embedder is not None and use_semantic_inventory
            else None
        )
        self.router = Router(branches, inventory_detector=inventory_detector)
        self.planner: Planner = build_planner(model, catalog, use_model=use_llm_planner)
        self.model = model
        self.embedder = embedder
        self.budget_store = budget_store
        self.quote_store = quote_store
        self.contacts = contacts or ContactDirectory(())
        self.roster = roster
        self.mailer = mailer or build_mailer(api_key="", from_address="")
        self.audit_log = audit_log
        self.use_llm_composer = use_llm_composer
        self._system_prompt = system_prompt
        self.executor = Executor(
            catalog=catalog,
            resolver=self.resolver,
            contacts=self.contacts,
            budget_store=budget_store,
            quote_store=quote_store,
            roster=roster,
            audit_log=audit_log,
        )

    @classmethod
    def load(cls, settings: Settings | None = None, **overrides: object) -> Pipeline:
        """Build a pipeline from configuration.

        Loading is total: a missing index yields keyword-free retrieval rather
        than a crash, and an unconfigured model yields deterministic answers.
        A missing *corpus* is fatal, because without it there are no verdicts
        and the assistant has nothing truthful to say.

        An embedding-contract mismatch disables dense retrieval rather than
        refusing to start. Cosine distance across models is meaningless, so
        the alternative to degrading would be quietly wrong ranks.
        """
        settings = settings or get_settings()
        catalog = load_catalog(Manifest.load(settings.documents_dir)).catalog
        index = KnowledgeIndex.load_local(settings.local_index_path)
        embedder = build_embedder(settings) if settings.use_dense_retrieval else None
        budget_store = build_budget_store(
            xlsx_path=settings.budget_xlsx_path,
            spreadsheet_id=settings.budget_spreadsheet_id,
            credentials_path=settings.google_application_credentials,
            cache_ttl_seconds=settings.budget_cache_ttl_seconds,
        )
        branches = tuple(branch.name for branch in budget_store.branches()) if budget_store else ()
        quote_store = load_quote_store(
            settings.quote_rate_card_path,
            spreadsheet_id=settings.budget_spreadsheet_id,
            credentials_path=settings.google_application_credentials,
            # Lets a sheet row naming a service the corpus has no document for
            # be reported at startup rather than silently priced into nothing.
            known_items=catalog.item_ids,
        )
        contacts = load_contacts(settings.contacts_path)
        roster = load_roster(
            settings.budget_xlsx_path,
            spreadsheet_id=settings.budget_spreadsheet_id,
            credentials_path=settings.google_application_credentials,
        )
        mailer = build_mailer(
            api_key=settings.mail_api_key,
            from_address=settings.mail_from_address,
            provider=settings.mail_provider,
        )
        audit_log = build_audit_store(
            backend=settings.audit_backend,
            jsonl_path=settings.audit_log_path,
            gcp_project_id=settings.gcp_project_id,
            firestore_database=settings.firestore_database,
            credentials_path=settings.google_application_credentials,
        )

        if index.is_empty:
            logger.warning(
                "pipeline.no_index",
                detail="retrieval disabled; verdicts still resolve by name and alias",
            )
        elif index.has_embeddings and embedder is not None:
            try:
                index.verify_contract(embedder.contract)
            except IndexContractError as exc:
                logger.error("pipeline.embed_contract_mismatch", error=str(exc))
                embedder = None
        elif index.has_embeddings and embedder is None:
            logger.info(
                "pipeline.embeddings_idle",
                detail="index carries vectors but no embedder is configured; keyword-only",
            )

        return cls(
            catalog,
            index,
            model=build_model(settings),
            embedder=embedder,
            system_prompt=load_system_prompt(settings.system_prompt_path),
            branches=branches,
            budget_store=budget_store,
            quote_store=quote_store,
            contacts=contacts,
            roster=roster,
            mailer=mailer,
            audit_log=audit_log,
            use_semantic_inventory=settings.use_semantic_inventory,
            use_llm_planner=settings.use_llm_planner,
            use_llm_composer=settings.use_llm_composer,
            **overrides,
        )

    def plan_for(
        self,
        question: str,
        route: Route,
        state: ConversationState,
        history: tuple[HistoryTurn, ...] = (),
    ) -> Plan:
        """Which lookups this turn needs. Never raises: a failed plan is a rule plan."""
        if isinstance(self.planner, ModelPlanner):
            return self.planner.plan(question, route, state, history)
        return self.planner.plan(question, route, state)

    def prepare(
        self,
        question: str,
        state: ConversationState | None = None,
        history: tuple[HistoryTurn, ...] = (),
    ) -> _Turn:
        """Everything up to the wording: plan, lookups, facts.

        Exposed so a turn can be inspected without generating — which is how
        ``scripts.ask --prompt`` shows what the model would be told.
        """
        state = state or ConversationState()
        route = self.router.route(question, state)
        plan = self.plan_for(question, route, state, history)
        resolution, retrieval = self._lookup(question, plan, route)

        confirm = (
            pending_from_state(state)
            if plan.wants(Capability.MAIL) and state.awaiting_action_confirm
            else None
        )
        facts = self.executor.run(
            question,
            plan,
            route,
            state,
            SessionIdentity(),
            history,
            resolution=resolution,
            retrieval=retrieval,
            confirm=confirm,
            mailer=self.mailer,
        )
        return _Turn(route, plan, resolution, retrieval, facts)

    def _lookup(
        self, question: str, plan: Plan, route: Route
    ) -> tuple[Resolution, RetrievalResult]:
        """Resolve and retrieve, but only for turns that are about a service."""
        if not plan.needs_a_service:
            return Resolution(Outcome.UNKNOWN, question), RetrievalResult(mode="skipped")

        resolution = self.executor.resolve(question, plan, route)
        retrieval = self.retriever.retrieve(
            question,
            limit=EVIDENCE_LIMIT,
            query_vector=self._query_vector(question),
            force_item_ids=resolution.force_item_ids,
        )
        return resolution, retrieval

    def _run_turn(
        self,
        question: str,
        state: ConversationState,
        history: tuple[HistoryTurn, ...],
        identity: SessionIdentity,
        conversation_id: str | None = None,
    ) -> _Turn:
        """Plan and execute one turn, with the real session identity."""
        route = self.router.route(question, state)
        plan = self.plan_for(question, route, state, history)
        resolution, retrieval = self._lookup(question, plan, route)

        confirm = (
            pending_from_state(state)
            if plan.wants(Capability.MAIL) and state.awaiting_action_confirm
            else None
        )
        facts = self.executor.run(
            question,
            plan,
            route,
            state,
            identity,
            history,
            resolution=resolution,
            retrieval=retrieval,
            confirm=confirm,
            mailer=self.mailer,
            conversation_id=conversation_id or state.conversation_id,
        )
        return _Turn(route, plan, resolution, retrieval, facts)

    def answer(
        self,
        question: str,
        state: ConversationState | None = None,
        history: tuple[HistoryTurn, ...] = (),
        *,
        identity: SessionIdentity | None = None,
    ) -> Answer:
        state = state or ConversationState()
        identity = identity or SessionIdentity()
        conversation_id = state.conversation_id or new_conversation_id(identity.subject)

        turn = self._run_turn(question, state, history, identity, conversation_id)
        worded = word_answer(
            self._composer(),
            turn.facts,
            question,
            history,
            system_prompt=self._system_prompt,
        )

        answer = self._assemble(
            turn, worded, conversation_id, identity, state=state
        )
        self._audit(
            conversation_id,
            question,
            answer,
            identity,
            outcome=turn.facts.audit_outcome,
            email=turn.facts.email,
            facts=turn.facts,
        )
        logger.info(
            "pipeline.answered",
            question=question,
            detail=answer.explain(),
            tokens=answer.tokens,
        )
        return answer

    def stream(
        self,
        question: str,
        state: ConversationState | None = None,
        history: tuple[HistoryTurn, ...] = (),
        *,
        identity: SessionIdentity | None = None,
    ) -> Iterator[StreamStart | TextPiece | StreamEnd]:
        """Answer incrementally: one :class:`StreamStart`, then text, then one
        :class:`StreamEnd`.
        """
        state = state or ConversationState()
        identity = identity or SessionIdentity()
        conversation_id = state.conversation_id or new_conversation_id(identity.subject)

        turn = self._run_turn(question, state, history, identity, conversation_id)
        next_state = _carry_forward(
            turn.route,
            turn.plan,
            turn.resolution,
            identity.branch,
            conversation_id=conversation_id,
            pending=turn.facts.pending,
            prior=state,
            budget=turn.facts.budget,
        )

        # The decision is known before a word is written, so it goes out first:
        # a dropped connection mid-answer still delivered the consequences.
        yield StreamStart(
            route=turn.route,
            resolution=turn.resolution,
            citations=turn.citations,
            notes=turn.facts.notes,
            next_state=next_state,
            actions=turn.facts.actions,
        )

        # Audited in a finally, because a browser that navigates away mid-answer
        # closes the generator and everything after the last yield is skipped.
        # The widget streams every turn, so leaving it after the final yield
        # meant a dropped connection lost the record of an email being sent.
        worded: Worded | None = None
        try:
            for piece in stream_wording(
                self._composer(),
                turn.facts,
                question,
                history,
                system_prompt=self._system_prompt,
            ):
                if isinstance(piece, Worded):
                    worded = piece
                    continue
                yield TextPiece(piece)

            assert worded is not None
            yield StreamEnd(
                worded.text,
                worded.source,
                degraded=worded.degraded,
                truncated=worded.truncated,
            )
        finally:
            self._audit(
                conversation_id,
                question,
                self._assemble(
                    turn,
                    # No wording means the turn was abandoned before it
                    # finished. Recorded as truncated rather than invented.
                    worded
                    or Worded(text="", source=DETERMINISTIC, degraded=True, truncated=True),
                    conversation_id,
                    identity,
                    state=state,
                ),
                identity,
                outcome=turn.facts.audit_outcome,
                email=turn.facts.email,
                facts=turn.facts,
            )

    def _composer(self) -> LanguageModel | None:
        """The model allowed to write this turn's wording, if any."""
        return self.model if self.use_llm_composer else None

    def _assemble(
        self,
        turn: _Turn,
        worded: Worded,
        conversation_id: str,
        identity: SessionIdentity,
        *,
        state: ConversationState,
    ) -> Answer:
        return Answer(
            text=worded.text,
            route=turn.route,
            resolution=turn.resolution,
            citations=turn.citations,
            source=worded.source,
            degraded=worded.degraded,
            notes=turn.facts.notes,
            next_state=_carry_forward(
                turn.route,
                turn.plan,
                turn.resolution,
                identity.branch,
                conversation_id=conversation_id,
                pending=turn.facts.pending,
                prior=state,
                budget=turn.facts.budget,
            ),
            actions=turn.facts.actions,
            plan=turn.plan,
            satisfied=turn.facts.satisfied,
            tokens=(turn.plan.tokens if turn.plan else 0) + worded.tokens,
        )

    def _audit(
        self,
        conversation_id: str,
        question: str,
        answer: Answer,
        identity: SessionIdentity,
        *,
        outcome: str | None = None,
        email: dict[str, object] | None = None,
        facts: FactPack | None = None,
    ) -> None:
        if self.audit_log is None:
            return
        resolved_outcome = outcome
        if resolved_outcome is None:
            if answer.next_state.pending_action_kind:
                resolved_outcome = OUTCOME_EMAIL_PENDING
            else:
                resolved_outcome = OUTCOME_CHAT_ONLY
        self.audit_log.append(
            AuditEvent(
                conversation_id=conversation_id,
                kind="turn",
                payload={
                    "user_message": question,
                    "assistant_message": answer.text,
                    "intent": answer.route.intent.value,
                    "status": answer.status.value if answer.status else None,
                    "source": answer.source,
                    "tokens": answer.tokens,
                    "outcome": resolved_outcome,
                    "email": email,
                    "actions": [action.id for action in answer.actions],
                    "pending_action_kind": answer.next_state.pending_action_kind,
                    "active_tool": answer.next_state.active_tool,
                    "budget_country": answer.next_state.budget_country,
                    "budget_branch": answer.next_state.budget_branch,
                    "budget_month": answer.next_state.budget_month,
                    # "person", not "subject": the turn also records an email
                    # subject line, and one of those names a human.
                    "person": identity.subject,
                    "role": identity.role,
                    "country": identity.country,
                    "branch": identity.branch,
                    # Why the turn answered as it did. Without this a bad reply
                    # can only be diagnosed by reproducing it locally.
                    "trace": _trace(answer.plan, facts),
                },
            )
        )

    def _query_vector(self, question: str) -> tuple[float, ...] | None:
        """Embed the question when both sides of the contract are present."""
        if self.embedder is None or not self.index.has_embeddings:
            return None
        return self.embedder.embed_query(question)


def pending_from_state(state: ConversationState) -> PendingAction:
    """Rebuild the pending mail action a previous turn left in state."""
    assert state.pending_action_kind is not None
    return PendingAction(
        kind=state.pending_action_kind,
        service_id=state.pending_service_id,
        quote_amount=state.pending_quote_amount,
        currency=state.pending_currency or "GBP",
        recipient_country=state.pending_recipient_country,
        recipient_name=state.pending_recipient_name,
        needs_country=state.pending_needs_country,
    )


@dataclass(frozen=True, slots=True)
class _Turn:
    """One turn's decisions and findings, before anything is worded."""

    route: Route
    plan: Plan
    resolution: Resolution
    retrieval: RetrievalResult
    facts: FactPack

    @property
    def citations(self) -> tuple[str, ...]:
        if self.facts.citations:
            return self.facts.citations
        # A Yes/No on a pending email looked nothing up, so it cites nothing.
        if Capability.MAIL in self.facts.satisfied:
            return ()
        # The catalogue answers these outright; no search was involved.
        if {Capability.LIST, Capability.CAPABILITIES} & set(self.facts.satisfied):
            return CATALOG_CITATION
        return NO_CITATIONS

    def briefing(self) -> str:
        """What the model would be told for this turn."""
        from app.orchestrator.wording import build_briefing

        return build_briefing(self.facts, self.route.message)


def _trace(plan: Plan | None, facts: FactPack | None) -> dict[str, object]:
    """The audit trail's account of how a turn was decided."""
    return {
        "planned": [capability.value for capability in plan.capabilities] if plan else [],
        "satisfied": [capability.value for capability in facts.satisfied] if facts else [],
        "slots": plan.slots.filled() if plan else {},
        "planner": plan.source if plan else None,
        "reading": plan.reading if plan else None,
    }


def _carry_forward(
    route: Route,
    plan: Plan,
    resolution: Resolution,
    session_branch: str | None = None,
    *,
    conversation_id: str | None = None,
    pending: PendingAction | None = None,
    prior: ConversationState | None = None,
    budget: BudgetToolResult | None = None,
) -> ConversationState:
    """What the next turn needs to know about this one."""
    branch = route.branch or session_branch
    active_tool: str | None = None
    budget_country: str | None = None
    budget_branch: str | None = None
    budget_month: str | None = None
    # Sticky only when the ledger was the point of the turn. A price that
    # happened to mention a budget must not capture the next question.
    if plan.primary is Capability.BUDGET:
        active_tool = "budget"
        if budget is not None and not (
            budget.ask_branch
            and budget.resolved_country is None
            and budget.resolved_branch is None
        ):
            budget_country = budget.resolved_country
            budget_branch = budget.resolved_branch
            budget_month = budget.resolved_month
        elif prior is not None:
            # Ask-branch with no new scope — keep prior sticky slots.
            budget_country = prior.budget_country
            budget_branch = prior.budget_branch
            budget_month = budget.resolved_month if budget else prior.budget_month
        elif budget is not None:
            budget_month = budget.resolved_month
    return ConversationState(
        pending_candidates=(
            resolution.force_item_ids if resolution.outcome is Outcome.AMBIGUOUS else ()
        ),
        last_item_ids=resolution.force_item_ids,
        last_branch=branch,
        last_intent=route.intent,
        conversation_id=conversation_id,
        pending_action_kind=pending.kind if pending else None,
        pending_service_id=pending.service_id if pending else None,
        pending_quote_amount=pending.quote_amount if pending else None,
        pending_currency=pending.currency if pending else "GBP",
        pending_recipient_country=pending.recipient_country if pending else None,
        pending_recipient_name=pending.recipient_name if pending else None,
        pending_needs_country=pending.needs_country if pending else False,
        active_tool=active_tool,
        budget_country=budget_country,
        budget_branch=budget_branch,
        budget_month=budget_month,
    )
