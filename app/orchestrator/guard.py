"""Checking a generated reply against the facts it was given.

The model is asked for wording, not judgement, but "asked" is not a guarantee.
This is the part that makes the guarantee: a reply is read back before it is
shown, and if it contains a figure the facts do not contain, or contradicts the
verdict that was looked up, it is discarded and the deterministic wording is
used instead.

Both checks are deliberately narrow. A guard that fires on innocent phrasing
would push every turn back to template English and quietly undo the reason for
having a model at all, so this looks for the two failures that actually cost
money:

- **A number nobody looked up.** Every figure in the facts is permitted; a new
  one is invented, whatever it is a price of.
- **A verdict turned upside down.** Saying "free of charge" about something that
  needs a purchase order is the single most expensive sentence this product can
  produce.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

from app.core.types import Status
from app.orchestrator.facts import FactPack, figures_in

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
_SENT_CLAIM = re.compile(
    r"\b(i'?ve sent|i have sent|email (has been |was )?sent|sent to)\b",
    re.IGNORECASE,
)


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

    if _SENT_CLAIM.search(text) and facts.email is None:
        return Violation("mail", "the reply claims an email was sent; none was")

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
