"""Checking a generated reply against the facts it was given.

The model is asked for wording, not judgement, but "asked" is not a guarantee.
This is the part that makes the guarantee: a reply is read back before it is
shown, and if it contains a figure the facts do not contain, or contradicts the
verdict that was looked up, it is discarded and the deterministic wording is
used instead.

The checks are deliberately narrow. A guard that fires on innocent phrasing
would push every turn back to template English and quietly undo the reason for
having a model at all, so this looks for the failures that actually cost money:

- **A number nobody looked up.** Every figure in the facts is permitted; a new
  one is invented, whatever it is a price of.
- **A verdict turned upside down.** Saying "free of charge" about something that
  needs a purchase order is the single most expensive sentence this product can
  produce.
- **A verdict for a service nobody looked up.** One message can ask about two
  services, and only one is checked. "Good news on the goals dashboard
  though, that's something we can definitely help with" gives a verdict no
  lookup produced, and would be a free promise for anything chargeable.
- **The right figures about the wrong country.** A budget answer that names a
  country the lookup was not about is wrong even when every number in it is
  real, and it reads exactly as authoritative as a correct one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

from app.core.keys import content_tokens
from app.core.types import Status
from app.orchestrator.facts import FactPack, figures_in
from app.orchestrator.resolver import STEM_LENGTH

__all__ = ["Violation", "inspect"]

logger = structlog.get_logger(__name__)

SMALLEST_CHECKED_FIGURE = 20.0
"""Below this, a number is almost always a count, a list position or a month
day rather than money. Checking them produced false positives on replies that
said "3 of those sit with your local team", which is a fact about the list."""

_CURRENCY_FIGURE = re.compile(
    r"(?:[£$€]\s?\d[\d,]*(?:\.\d+)?)|(?:\d[\d,]*(?:\.\d+)?\s?(?:gbp|eur|usd|pounds?|k\b))",
    re.IGNORECASE,
)

_FREE_CLAIM = re.compile(
    r"\b(free of charge|at no (extra )?cost|no charge|won'?t cost you|"
    r"included in (our|the) scope|covered by central marketing|foc)\b",
    re.IGNORECASE,
)
_CHARGE_CLAIM = re.compile(
    r"\b(needs? a quote|will need quoting|has to be quoted|chargeable|"
    r"purchase order|raise a po|you'?ll be charged)\b",
    re.IGNORECASE,
)
_REFUSAL_CLAIM = re.compile(
    r"\b(out of scope|can'?t take this on|cannot take this on|we don'?t do this)\b",
    re.IGNORECASE,
)
_LOCAL_CLAIM = re.compile(
    r"\b(your local (site|team)|local site|ops team|handled locally|sits with (your|the) local)\b",
    re.IGNORECASE,
)
_ASSURANCE_CLAIM = re.compile(
    r"\b(good news|can (definitely |certainly |absolutely )?help( you)? with|"
    r"(we|central marketing|the central marketing team) (can|could|will) "
    r"(do|handle|cover|sort|take care of)|(is|that'?s|it'?s) covered|we cover|"
    r"happy to help with)\b",
    re.IGNORECASE,
)
"""Reassurance that works as a verdict without using a verdict word.

Only consulted beside a service that was not looked up. On its own "we can
help with that" is ordinary friendliness; next to a service nobody checked it
is a promise, and the one this was written for was exactly that."""

_CLAUSE_BREAK = re.compile(r"(?<=[.!?;])\s+")

_SENT_CLAIM = re.compile(
    r"\b(i'?ve sent|i have sent|email (has been |was )?sent|sent to)\b",
    re.IGNORECASE,
)

_COUNTRY_ALIASES = {
    "united kingdom": "united kingdom",
    "uk": "united kingdom",
    "britain": "united kingdom",
    "france": "france",
    "paris": "france",
    "canada": "canada",
    "australia": "australia",
}
"""The countries the tracker covers, and the words people use for them.

Only countries, not sites. A reply naming the wrong *branch* is also wrong, but
the branch vocabulary is not in the facts, and guessing at it would fire on
turns that legitimately mention a neighbouring site."""


@dataclass(frozen=True, slots=True)
class Violation:
    kind: str
    """``figure`` | ``verdict`` | ``mail``. Grouped so the logs can be counted."""

    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.detail}"


def inspect(text: str, facts: FactPack) -> Violation | None:
    """The first problem found in a generated reply, or ``None`` if it is safe."""
    if not text.strip():
        return Violation("empty", "the model returned nothing")

    if figure := _invented_figure(text, facts):
        return Violation("figure", f"{figure} appears in the reply but not in the facts")

    if verdict := _contradicted_verdict(text, facts):
        return Violation("verdict", verdict)

    if unchecked := _verdict_for_unchecked_service(text, facts):
        return Violation("verdict", unchecked)

    if _SENT_CLAIM.search(text) and facts.email is None:
        return Violation("mail", "the reply claims an email was sent; none was")

    if place := _wrong_country(text, facts):
        return Violation("place", place)

    return None


def _stems(text: str) -> set[str]:
    return {token[:STEM_LENGTH] for token in content_tokens(text)}


def _verdict_for_unchecked_service(text: str, facts: FactPack) -> str | None:
    """A verdict or reassurance given beside a service that was never looked up.

    The services to watch for are the ones the planner listed as asked about but
    not looked up, in the user's own words, so this matches those words rather
    than guessing from the whole catalogue — which, measured, confused
    "international" with Translation & localisation.

    A clause counts as being about one of them when it carries at least half of
    that phrase's words, not counting words the looked-up service shares. The
    clause after it is read too, because the reply this was written for named
    the service in one sentence and promised it in the next — unless that next
    clause is plainly about the looked-up service, whose verdict belongs there.
    """
    others = facts.plan.slots.other_services
    if not others or facts.scope is None:
        return None
    looked_up: set[str] = set()
    for candidate in facts.scope.candidates:
        looked_up |= _stems(candidate.item.item)
    claims = (_FREE_CLAIM, _CHARGE_CLAIM, _REFUSAL_CLAIM, _LOCAL_CLAIM, _ASSURANCE_CLAIM)
    clauses = [c for c in _CLAUSE_BREAK.split(text.strip()) if c]
    for phrase in others:
        words = _stems(phrase) - looked_up
        if not words:
            continue
        needed = max(1, (len(words) + 1) // 2)
        for index, clause in enumerate(clauses):
            if len(words & _stems(clause)) < needed:
                continue
            window = [clause]
            if index + 1 < len(clauses) and not (_stems(clauses[index + 1]) & looked_up):
                window.append(clauses[index + 1])
            if any(claim.search(part) for part in window for claim in claims):
                return f"the reply gives a verdict for {phrase!r}, which was not looked up"
    return None


def _wrong_country(text: str, facts: FactPack) -> str | None:
    """A budget reply that talks about a country the lookup was not about.

    Sticky budget threads are where this bites: after a question about Canada,
    "and for the uk?" is looked up correctly, and a model that keeps its previous
    framing answers about Canada with no figure to betray it.
    """
    allowed = {
        canonical
        for canonical in (
            _COUNTRY_ALIASES.get((snapshot.branch.country or "").strip().lower())
            for snapshot in facts.budget_snapshots
        )
        if canonical
    }
    if facts.budget is not None:
        resolved = _COUNTRY_ALIASES.get((facts.budget.resolved_country or "").strip().lower())
        if resolved:
            allowed.add(resolved)
    if not allowed:
        return None

    lowered = text.lower()
    for alias, canonical in _COUNTRY_ALIASES.items():
        if canonical in allowed:
            continue
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return (
                f"the reply is about {alias}, but the budget looked up was for "
                f"{', '.join(sorted(allowed))}"
            )
    return None


def _invented_figure(text: str, facts: FactPack) -> str | None:
    permitted = facts.permitted_figures()
    for raw in figures_in(text):
        if raw in permitted:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if value < SMALLEST_CHECKED_FIGURE and not _CURRENCY_FIGURE.search(text):
            continue
        return raw
    return None


def _contradicted_verdict(text: str, facts: FactPack) -> str | None:
    verdict = facts.verdict

    if verdict is None:
        # No verdict was reached, so no verdict may be implied. A list or a
        # budget answer legitimately mentions statuses, so only guard turns
        # where a service lookup was attempted and failed.
        if facts.scope is None or facts.listing or facts.capability_summary:
            return None
        if _FREE_CLAIM.search(text) or _REFUSAL_CLAIM.search(text):
            return "the reply states a verdict, but none was looked up"
        return None

    if verdict is Status.IN_SCOPE and (_CHARGE_CLAIM.search(text) or _REFUSAL_CLAIM.search(text)):
        return "the service is in scope, but the reply implies a charge or a refusal"
    if verdict is Status.QUOTE_REQUIRED and _FREE_CLAIM.search(text):
        return "the service needs a quote, but the reply implies it is free"
    if verdict is Status.OUT_OF_SCOPE and _FREE_CLAIM.search(text):
        return "the service is out of scope, but the reply implies we cover it"
    if verdict is Status.LOCAL and _FREE_CLAIM.search(text) and not _LOCAL_CLAIM.search(text):
        return "the service is local, but the reply implies central marketing covers it"
    return None
