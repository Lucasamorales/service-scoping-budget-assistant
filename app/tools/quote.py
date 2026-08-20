"""Quoting tool — prices come only from the rate card, never the model."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.types import ServiceItem
from app.store.budget import BudgetSnapshot, BudgetStore
from app.store.quote import QuoteStore
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


def quote_for(
    item: ServiceItem,
    store: QuoteStore | None,
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
    if price == "Variable":
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
            over = amount > remaining
            budget_text = (
                f" You currently have **{remaining:,.2f} {store.currency}** left in "
                f"**{snapshot.branch.name}** for **{snapshot.month}**."
            )
            if over:
                budget_text += (
                    " That quote is above the remaining budget, so you'll need to request "
                    "additional funds from your Country Manager."
                )

    text = (
        f"We can do **{item.display_name}** on demand. The estimated cost is "
        f"**{amount:,.2f} {store.currency}** (tier {tier}).{budget_text} "
        "Would you like me to email your Country Manager to request a Purchase Order for this?"
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
