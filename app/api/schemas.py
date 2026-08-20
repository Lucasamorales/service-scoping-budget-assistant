"""Request and response bodies.

Conversation state travels to the client and back rather than living on the
server. That keeps the service stateless, so Cloud Run can scale it
horizontally and restart it freely with no session affinity and no shared
store. Firestore-backed history can be added later for audit and analytics
without changing this contract.

Returned state is not trusted on the way back in. A caller can put any item id
in it, so ids are checked against the catalog before use. The blast radius is
small - the worst a forged id achieves is a verdict the caller could have asked
for directly - but validating means a malformed client cannot produce a
confusing answer, and unknown ids are dropped rather than echoed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.api.session import Role
from app.core.types import Status
from app.orchestrator.history import HistoryTurn
from app.orchestrator.pipeline import Answer
from app.orchestrator.router import ConversationState
from app.tools.actions import Action

__all__ = [
    "MAX_HISTORY_MESSAGES",
    "MAX_MESSAGE_CHARS",
    "ActionModel",
    "CandidateOption",
    "ChatRequest",
    "ChatResponse",
    "HealthResponse",
    "HistoryMessage",
    "SessionRequest",
    "SessionResponse",
    "StateModel",
    "Verdict",
]

MAX_MESSAGE_CHARS = 2000
"""Hard cap on a single user message."""

MAX_HISTORY_CHARS = 12_000
"""Prior assistant turns can be long (full service catalogue). Kept separate
from ``MAX_MESSAGE_CHARS`` so a catalogue list does not 422 the next turn."""
"""Longer than any real scoping question. A cap here bounds prompt cost and
removes the easiest way to run up a bill or bury instructions in padding."""

MAX_CARRIED_IDS = 8
"""Ceiling on ids echoed back in state. The resolver never produces more than
a handful, so anything larger is a malformed or hostile client."""

MAX_HISTORY_MESSAGES = 12
"""Last six exchanges. Enough for continuity without flooding the prompt."""


class Base(BaseModel):
    """camelCase on the wire, snake_case in Python."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class StateModel(Base):
    """The previous turn, as the client received it."""

    pending_candidates: tuple[str, ...] = Field(default=(), max_length=MAX_CARRIED_IDS)
    last_item_ids: tuple[str, ...] = Field(default=(), max_length=MAX_CARRIED_IDS)
    last_branch: str | None = Field(default=None, max_length=100)
    conversation_id: str | None = Field(default=None, max_length=64)
    pending_action_kind: str | None = Field(default=None, max_length=40)
    pending_service_id: str | None = Field(default=None, max_length=200)
    pending_quote_amount: float | None = None
    pending_currency: str = Field(default="GBP", max_length=8)
    pending_recipient_country: str | None = Field(default=None, max_length=80)
    pending_recipient_name: str | None = Field(default=None, max_length=120)
    pending_needs_country: bool = False
    active_tool: str | None = Field(default=None, max_length=40)
    budget_country: str | None = Field(default=None, max_length=80)
    budget_branch: str | None = Field(default=None, max_length=100)
    budget_month: str | None = Field(default=None, max_length=16)

    def to_state(self, known: frozenset[str]) -> ConversationState:
        """Convert to the internal type, dropping ids the catalog does not have."""
        service_id = self.pending_service_id if self.pending_service_id in known else None
        return ConversationState(
            pending_candidates=tuple(i for i in self.pending_candidates if i in known),
            last_item_ids=tuple(i for i in self.last_item_ids if i in known),
            last_branch=self.last_branch,
            conversation_id=self.conversation_id,
            pending_action_kind=self.pending_action_kind,
            pending_service_id=service_id,
            pending_quote_amount=self.pending_quote_amount,
            pending_currency=self.pending_currency or "GBP",
            pending_recipient_country=self.pending_recipient_country,
            pending_recipient_name=self.pending_recipient_name,
            pending_needs_country=self.pending_needs_country,
            active_tool=self.active_tool,
            budget_country=self.budget_country,
            budget_branch=self.budget_branch,
            budget_month=self.budget_month,
        )

    @classmethod
    def from_state(cls, state: ConversationState) -> StateModel:
        return cls(
            pending_candidates=state.pending_candidates,
            last_item_ids=state.last_item_ids,
            last_branch=state.last_branch,
            conversation_id=state.conversation_id,
            pending_action_kind=state.pending_action_kind,
            pending_service_id=state.pending_service_id,
            pending_quote_amount=state.pending_quote_amount,
            pending_currency=state.pending_currency,
            pending_recipient_country=state.pending_recipient_country,
            pending_recipient_name=state.pending_recipient_name,
            pending_needs_country=state.pending_needs_country,
            active_tool=state.active_tool,
            budget_country=state.budget_country,
            budget_branch=state.budget_branch,
            budget_month=state.budget_month,
        )


class HistoryMessage(Base):
    """One prior turn the client carries for wording continuity."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_HISTORY_CHARS)

    def to_turn(self) -> HistoryTurn:
        return HistoryTurn(role=self.role, content=self.content)


class ChatRequest(Base):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    state: StateModel | None = None
    history: tuple[HistoryMessage, ...] = Field(default=(), max_length=MAX_HISTORY_MESSAGES)

    def history_turns(self) -> tuple[HistoryTurn, ...]:
        return tuple(message.to_turn() for message in self.history)


class Verdict(Base):
    """The scope decision, separate from the prose that explains it."""

    status: Status
    meaning: str
    service: str


class CandidateOption(Base):
    """One service the user may mean, when the resolver must ask."""

    id: str
    label: str


class ActionModel(Base):
    """Server-driven button. ``message`` actions send that text as the next turn."""

    id: str
    label: str
    kind: Literal["message", "link"] = "message"
    message: str | None = None
    url: str | None = None

    @classmethod
    def from_action(cls, action: Action) -> ActionModel:
        return cls(
            id=action.id,
            label=action.label,
            kind=action.kind,
            message=action.message,
            url=action.url,
        )


def candidates_from(answer: Answer) -> tuple[CandidateOption, ...]:
    """Options for the clarification UI. Empty unless the turn is ambiguous."""
    if not answer.awaiting_answer:
        return ()
    return tuple(
        CandidateOption(id=item.item_id, label=item.display_name)
        for item in answer.resolution.items
    )


def actions_from(answer: Answer) -> tuple[ActionModel, ...]:
    return tuple(ActionModel.from_action(action) for action in answer.actions)


class ChatResponse(Base):
    text: str
    verdict: Verdict | None = None
    citations: tuple[str, ...] = ()
    source: str
    """``deterministic`` or the model name, so a degraded turn is attributable."""

    degraded: bool = False
    needs_a_human: bool = False
    awaiting_answer: bool = False
    """The assistant asked a question. The client should send the returned
    state back with the user's reply."""

    candidates: tuple[CandidateOption, ...] = ()
    """When ``awaiting_answer`` is true, the services to choose between."""

    actions: tuple[ActionModel, ...] = ()
    """Yes/No (and similar) CTAs driven by business flows."""

    notes: tuple[str, ...] = ()
    state: StateModel

    @classmethod
    def from_answer(cls, answer: Answer) -> ChatResponse:
        verdict = None
        if answer.status is not None and answer.resolution.status_meaning:
            verdict = Verdict(
                status=answer.status,
                meaning=answer.resolution.status_meaning,
                service=answer.resolution.candidates[0].item.display_name,
            )

        return cls(
            text=answer.text,
            verdict=verdict,
            citations=answer.citations,
            source=answer.source,
            degraded=answer.degraded,
            needs_a_human=answer.needs_a_human,
            awaiting_answer=answer.awaiting_answer,
            candidates=candidates_from(answer),
            actions=actions_from(answer),
            notes=answer.notes,
            state=StateModel.from_state(answer.next_state),
        )


class SessionRequest(Base):
    """Credentials for minting a session on the internal MVP page."""

    password: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=2, max_length=120)
    """Display name required so audit logs record who asked."""

    role: Role = Role.ACCOUNT_MANAGER
    country: str | None = Field(default=None, max_length=80)
    branch: str | None = Field(default=None, max_length=120)


class SessionResponse(Base):
    token: str
    expires_at: int
    role: Role
    subject: str | None = None
    country: str | None = None
    branch: str | None = None


class HealthResponse(Base):
    """What is working, stated per subsystem."""

    status: str
    services: int
    chunks: int
    index_build: str = ""
    model: str = "deterministic"
    embeddings: bool = False
    auth_required: bool = False
    mail: bool = False
    budget: bool = False
    quote: bool = False
