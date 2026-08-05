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

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.api.session import Role
from app.core.types import Status
from app.orchestrator.pipeline import Answer
from app.orchestrator.router import ConversationState

__all__ = [
    "MAX_MESSAGE_CHARS",
    "ChatRequest",
    "ChatResponse",
    "HealthResponse",
    "SessionRequest",
    "SessionResponse",
    "StateModel",
    "Verdict",
]

MAX_MESSAGE_CHARS = 2000
"""Longer than any real scoping question. A cap here bounds prompt cost and
removes the easiest way to run up a bill or bury instructions in padding."""

MAX_CARRIED_IDS = 8
"""Ceiling on ids echoed back in state. The resolver never produces more than
a handful, so anything larger is a malformed or hostile client."""


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

    def to_state(self, known: frozenset[str]) -> ConversationState:
        """Convert to the internal type, dropping ids the catalog does not have."""
        return ConversationState(
            pending_candidates=tuple(i for i in self.pending_candidates if i in known),
            last_item_ids=tuple(i for i in self.last_item_ids if i in known),
            last_branch=self.last_branch,
        )

    @classmethod
    def from_state(cls, state: ConversationState) -> StateModel:
        return cls(
            pending_candidates=state.pending_candidates,
            last_item_ids=state.last_item_ids,
            last_branch=state.last_branch,
        )


class ChatRequest(Base):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    state: StateModel | None = None


class Verdict(Base):
    """The scope decision, separate from the prose that explains it.

    Given its own field so the widget can render it as a badge without parsing
    the answer text, and so a caller can act on it programmatically. Absent
    when the resolver reached no verdict, which is a real outcome rather than
    a missing value.
    """

    status: Status
    meaning: str
    service: str


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
            notes=answer.notes,
            state=StateModel.from_state(answer.next_state),
        )


class SessionRequest(Base):
    """Credentials for minting a session on the internal MVP page."""

    password: str = Field(min_length=1, max_length=200)
    subject: str = Field(default="internal", max_length=120)
    role: Role = Role.ACCOUNT_MANAGER
    country: str | None = Field(default=None, max_length=80)
    branch: str | None = Field(default=None, max_length=120)


class SessionResponse(Base):
    token: str
    expires_at: int
    role: Role
    country: str | None = None
    branch: str | None = None


class HealthResponse(Base):
    """What is working, stated per subsystem.

    Reports ``ok`` while running without a model or an index, because the
    assistant still answers correctly in both cases. Marking a degraded but
    functioning service unhealthy would have Cloud Run restart it in a loop,
    turning a reduced capability into an outage.
    """

    status: str
    services: int
    chunks: int
    index_build: str = ""
    model: str = "deterministic"
    embeddings: bool = False
    auth_required: bool = False
