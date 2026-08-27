"""What a turn needs looked up, separated from how the answer is worded.

The old design decided one intent per message and let that choice pick both the
tool and the sentence. A near-miss therefore produced a confident canned reply
instead of a worse-but-honest one, and a question that needed two facts — "do we
have budget for a photoshoot in Basingstoke" wants a price *and* a ledger — could
only ever get one.

A plan is a request for lookups, nothing more. It names capabilities and fills
slots; it cannot state a verdict, a price or a remaining balance, because those
come from the tools it selects. That is what makes it safe to let a language
model produce one: the worst a bad plan can do is look the wrong thing up, and
the reply says out loud which service it read the request as.

Plans come from :mod:`app.orchestrator.planner`, which prefers the model and
falls back to the rule router. Both produce this type, so everything downstream
is indifferent to which one ran.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum

from app.core.types import Status

__all__ = [
    "Capability",
    "Plan",
    "Slots",
    "status_filter_from",
]


class Capability(StrEnum):
    """A lookup the assistant can perform for a turn."""

    HANDOVER = "handover"
    """Must reach a person. Decided by rule only, never by a model."""

    SCOPE = "scope"
    """Is this in scope, refused, local, or does it need a quote?"""

    BUDGET = "budget"
    QUOTE = "quote"

    LIST = "list"
    """Inventory: the catalog, whole or filtered by section / status."""

    CAPABILITIES = "capabilities"
    """What the assistant itself can do — a summary, not the full catalog."""

    ROSTER = "roster"
    """Who owns an account or a country: the people directory."""

    MAIL = "mail"
    """Confirm or cancel the email the previous turn offered."""

    GREETING = "greeting"

    OUT_OF_REMIT = "out_of_remit"
    """A real subject this assistant has no business answering. Decided by rule
    only, never by a model, for the same reason handover is."""

    CLARIFY = "clarify"
    """Nothing could be identified. Ask, rather than guess."""

    @property
    def needs_a_service(self) -> bool:
        return self in {Capability.SCOPE, Capability.QUOTE}


_STATUS_FILTERS: dict[str, Status] = {
    "in_scope": Status.IN_SCOPE,
    "on_demand": Status.QUOTE_REQUIRED,
    "quote_required": Status.QUOTE_REQUIRED,
    "local": Status.LOCAL,
    "out_of_scope": Status.OUT_OF_SCOPE,
}


def status_filter_from(raw: str | None) -> Status | None:
    """Map a planner's status word onto the corpus enum, or ``None``.

    Unknown words resolve to ``None`` rather than raising: a filter we do not
    recognise should widen the answer, not fail the turn.
    """
    if not raw:
        return None
    return _STATUS_FILTERS.get(raw.strip().lower().replace("-", "_").replace(" ", "_"))


@dataclass(frozen=True, slots=True)
class Slots:
    """The details a capability needs, as the user expressed them.

    Every field is optional. A missing slot is filled by the tools from sticky
    state or the session, or asked about — it is never invented here.
    """

    service_phrase: str | None = None
    """The words naming the service, for the resolver. Not an item id: the
    resolver owns that mapping, and a model guessing ids would be a model
    choosing verdicts."""

    branch: str | None = None
    country: str | None = None
    month: str | None = None
    section: str | None = None
    status_filter: str | None = None

    @property
    def status(self) -> Status | None:
        return status_filter_from(self.status_filter)

    def filled(self) -> dict[str, str]:
        """Only the slots that carry a value, for logs and the audit trail."""
        return {
            name: value
            for name, value in (
                ("service_phrase", self.service_phrase),
                ("branch", self.branch),
                ("country", self.country),
                ("month", self.month),
                ("section", self.section),
                ("status_filter", self.status_filter),
            )
            if value
        }


@dataclass(frozen=True, slots=True)
class Plan:
    """The lookups for one turn, in the order they should be reported."""

    capabilities: tuple[Capability, ...]
    slots: Slots = field(default_factory=Slots)
    source: str = "rules"
    """``rules`` or the model name, so a bad plan can be attributed."""

    reading: str | None = None
    """How the request was understood, in the user's own terms. Surfaced in the
    reply when a service was inferred, so a misread is visible rather than
    silently authoritative."""

    tokens: int = 0
    """What planning this turn cost. Zero for the rule planner, which is free
    and is the point of having it."""

    def __post_init__(self) -> None:
        if not self.capabilities:
            object.__setattr__(self, "capabilities", (Capability.CLARIFY,))

    def wants(self, capability: Capability) -> bool:
        return capability in self.capabilities

    @property
    def primary(self) -> Capability:
        """The capability the answer leads with."""
        return self.capabilities[0]

    @property
    def needs_a_service(self) -> bool:
        return any(capability.needs_a_service for capability in self.capabilities)

    def with_slots(self, **updates: str | None) -> Plan:
        return replace(self, slots=replace(self.slots, **updates))

    def explain(self) -> str:
        detail = ", ".join(capability.value for capability in self.capabilities)
        slots = self.slots.filled()
        if slots:
            detail += " {" + ", ".join(f"{k}={v!r}" for k, v in slots.items()) + "}"
        return f"{detail} via {self.source}"
