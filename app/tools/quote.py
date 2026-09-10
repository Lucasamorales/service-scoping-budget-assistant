"""Quoting tool — prices come only from the rate card, never the model."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.types import ServiceItem
from app.store.budget import BudgetSnapshot, BudgetStore
from app.store.quote import RateCard
from app.tools.budget import answer_budget

__all__ = ["QuoteOutcome", "quote_for"]


@dataclass(frozen=True, slots=True)
class QuoteOutcome:
    kind: str
    """``priced`` | ``variable`` | ``missing``."""

    text: str
    tier: str | None = None
    price: float | None = None
    currency: str = "GBP"
    over_budget: bool = False
    remaining: float | None = None
    budget: BudgetSnapshot | None = None


_CURRENCY_SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€", "CAD": "CA$", "AUD": "A$"}


def _money(amount: float, currency: str) -> str:
    """Format a figure the way the approved quote copy writes it: £350.

    Trailing zeros are dropped because every tier on the rate card is a whole
    number and "£350.00" reads like an invoice rather than a ballpark. A price
    that is not whole keeps its pence rather than being rounded into a figure
    nobody will be charged.

    An unknown currency falls back to its code, which is worse to read and
    impossible to misread — the wrong symbol on a number is a lie about money.
    """
    symbol = _CURRENCY_SYMBOLS.get(currency.upper())
    figure = f"{amount:,.0f}" if float(amount).is_integer() else f"{amount:,.2f}"
    return f"{symbol}{figure}" if symbol else f"{figure} {currency.upper()}"


def quote_for(
    item: ServiceItem,
    store: RateCard | None,
    budget_store: BudgetStore | None,
    *,
    session_branch: str | None = None,
    question: str = "",
) -> QuoteOutcome:
    if store is None:
        return QuoteOutcome(
            kind="missing",
            text=(
                f"**{item.display_name}** needs a custom quote, but the rate card isn't "
                "loaded here. I can still ping your Account Manager to price it manually."
            ),
        )

    looked = store.lookup(item.item_id)
    if looked is None:
        return QuoteOutcome(
            kind="missing",
            text=(
                f"**{item.display_name}** is on demand, but it isn't on the rate card yet. "
                "I can ask your Account Manager to price it."
            ),
        )

    tier, price = looked
    # Two routes to the same answer. A ``Variable`` tier is the rate card
    # declining to name a number; an ``Automatic price: No`` bullet is the
    # document declining on behalf of a service whose tier covers only part of
    # the cost. Event attendance is the case that matters: the Scope tab tiers
    # the coordination work, but the bill is travel, hotels and food, and
    # quoting the tier alone would understate it by an unbounded amount.
    if price == "Variable" or _refuses_automatic_price(item):
        return QuoteOutcome(
            kind="variable",
            tier=tier,
            text=(
                f"**{item.display_name}** involves third-party or travel costs, so it needs a "
                "manual custom quote rather than an automatic price. Would you like me to send "
                "this to your Account Manager so they can price it?"
            ),
        )

    amount = float(price)
    budget_text = ""
    remaining: float | None = None
    over = False
    snapshot: BudgetSnapshot | None = None
    if budget_store is not None and (session_branch or question):
        budget_reply = answer_budget(
            question or f"budget at {session_branch}",
            budget_store,
            session_branch=session_branch,
        )
        if budget_reply.snapshot is not None:
            snapshot = budget_reply.snapshot
            remaining = snapshot.remaining
            if remaining is None:
                # No cap on the sheet means no balance to compare against. Saying
                # nothing about budget beats implying the quote clears one.
                budget_text = (
                    f" I can't tell what's left at {snapshot.branch.name} for "
                    f"{snapshot.month} — the tracker has no cap for it."
                )
            else:
                over = amount > remaining
                budget_text = (
                    f" You currently have {_money(remaining, store.currency)} left in "
                    f"{snapshot.branch.name} for {snapshot.month}."
                )
                if over:
                    budget_text += (
                        " That quote is above the remaining budget, so you'll need to request "
                        "additional funds from your Country Manager."
                    )

    # Stakeholder-approved copy, and it goes out exactly as written — see
    # FactPack.allows_generation, which stops the composer rewriting a priced
    # quote. The casing of "country manager" differs between the two sentences
    # because that is how the approved wording reads.
    text = (
        "This falls outside of the approved scope, and it's usually priced at "
        f"{_money(amount, store.currency)}. If you'd like to go ahead with it, you'll "
        "need a PO approved from your country manager. I can email your Country "
        f"Manager to kick things off.{budget_text}"
    )
    return QuoteOutcome(
        kind="priced",
        text=text,
        tier=tier,
        price=amount,
        currency=store.currency,
        over_budget=over,
        remaining=remaining,
        budget=snapshot,
    )


def _refuses_automatic_price(item: ServiceItem) -> bool:
    """Whether the document opted out of automatic tier pricing.

    Read permissively: the bullet is prose written by whoever maintains the
    corpus, so "No", "no - travel varies" and "No — costs are variable" must
    all count. Anything that does not start with a no is treated as consent,
    because the failure of a false negative here is a missing price and the
    failure of a false positive is a wrong one.
    """
    declared = (item.at_a_glance.automatic_price or "").strip().lower()
    return declared.startswith("no")
