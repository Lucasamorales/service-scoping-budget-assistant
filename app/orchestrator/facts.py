"""What a turn found out, before anybody decides how to say it.

Every capability writes its result here and nowhere else. Two things then read
it: the deterministic composer, which formats it directly, and the model, which
is shown it as a briefing and asked for wording. Because both read the same
object, the model can be turned off, fail, or be caught inventing a number, and
the answer that reaches the user still rests on identical facts.

The pack also carries its own permitted vocabulary — the figures that appeared
in the facts and the verdict that was looked up — so
:mod:`app.orchestrator.guard` can check a generated reply without re-deriving
anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from app.core.types import Chunk, Status
from app.orchestrator.plan import Capability, Plan
from app.orchestrator.resolver import Outcome, Resolution
from app.orchestrator.router import HandoverTopic
from app.store.budget import BudgetSnapshot
from app.store.contacts import Contact
from app.tools.actions import Action
from app.tools.budget import BudgetToolResult
from app.tools.flows import PendingAction
from app.tools.quote import QuoteOutcome

__all__ = ["FactPack", "figures_in"]

_FIGURE = re.compile(r"\d[\d,]*(?:\.\d+)?")

_STATUS_SENTENCE: dict[Status, str] = {
    Status.IN_SCOPE: "central marketing covers this at no cost to the site",
    Status.QUOTE_REQUIRED: "doable on demand, but it has to be quoted and raised on a PO first",
    Status.LOCAL: "the local site or ops team owns this, not central marketing",
    Status.OUT_OF_SCOPE: "central marketing will not take this on",
}


def figures_in(text: str) -> frozenset[str]:
    """Every number in a piece of text, normalised for comparison.

    Thousands separators and trailing zeros are dropped so that ``1,200``,
    ``1200`` and ``1200.00`` are one figure rather than three.
    """
    found = set()
    for raw in _FIGURE.findall(text or ""):
        cleaned = raw.replace(",", "")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        found.add(f"{value:.2f}".rstrip("0").rstrip("."))
    return frozenset(found)


@dataclass(frozen=True, slots=True)
class FactPack:
    """The facts for one turn, and the account of where they came from."""

    plan: Plan
    satisfied: tuple[Capability, ...] = ()
    """Capabilities that actually produced something. A planned lookup that
    found nothing does not appear here, which is how a misplan becomes a
    clarifying question instead of a confident answer."""

    handover: HandoverTopic | None = None
    out_of_remit: bool = False
    """The request was refused as outside what this assistant covers. Carries
    no subject of its own: naming one would imply an opinion about it."""

    scope: Resolution | None = None
    budget: BudgetToolResult | None = None
    quote: QuoteOutcome | None = None
    listing: str | None = None
    capability_summary: str | None = None
    roster: tuple[Contact, ...] = ()
    roster_note: str | None = None

    evidence: tuple[Chunk, ...] = ()
    citations: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    actions: tuple[Action, ...] = ()
    pending: PendingAction | None = None
    audit_outcome: str | None = None
    email: dict[str, object] | None = None

    fallback_text: str = ""
    """The deterministic answer. Used when the model is off, fails, or writes
    something the facts do not support."""

    @property
    def verdict(self) -> Status | None:
        if self.scope is None or not self.scope.decided:
            return None
        return self.scope.status

    @property
    def budget_snapshots(self) -> tuple[BudgetSnapshot, ...]:
        if self.budget is None:
            return ()
        return self.budget.snapshots or (
            (self.budget.snapshot,) if self.budget.snapshot else ()
        )

    @property
    def is_empty(self) -> bool:
        """Nothing was found, so the only honest reply is a question."""
        return not self.satisfied or self.satisfied == (Capability.CLARIFY,)

    @property
    def allows_generation(self) -> bool:
        """Whether a model may word this turn at all.

        Handover text is quoted, not paraphrased: it is the one reply where a
        friendlier rewrite is a liability. An ambiguous shortlist is the same
        kind of thing — a truncated model list of options is worse than the
        composed question. Mail confirm/cancel is the third: history still
        contains the original request, and a model shown "No" plus that thread
        will re-answer the request instead of acknowledging the decline.

        A priced quote is the fourth, and the only one here that is a business
        decision rather than a technical one. The wording was written and
        approved by stakeholders, and approved wording that comes out slightly
        different every time has not really been approved. The composer is a
        good writer and would paraphrase it — the system prompt tells it to
        vary its phrasing — so the only way to honour "verbatim" is not to ask
        it. Variable and unpriced quotes are unaffected and still composed.
        """
        if self.handover is not None or self.out_of_remit:
            return False
        if self.scope is not None and self.scope.outcome is Outcome.AMBIGUOUS:
            return False
        if self.quote is not None and self.quote.kind == "priced":
            return False
        return Capability.MAIL not in self.satisfied

    def permitted_figures(self) -> frozenset[str]:
        """Numbers a reply is allowed to contain."""
        sources = [self.fallback_text, self.listing or "", self.capability_summary or ""]
        if self.quote is not None:
            sources.append(self.quote.text)
            for value in (self.quote.price, self.quote.remaining):
                if value is not None:
                    sources.append(f"{value:.2f}")
        for snapshot in self.budget_snapshots:
            figures = [f"{snapshot.spent:.2f}"]
            for value in (snapshot.cap, snapshot.remaining):
                if value is not None:
                    figures.append(f"{value:.2f}")
            sources.append(" ".join(figures))
        if self.budget is not None:
            sources.append(self.budget.text)
        return frozenset().union(*(figures_in(source) for source in sources))

    def with_satisfied(self, capability: Capability) -> FactPack:
        if capability in self.satisfied:
            return self
        return replace(self, satisfied=(*self.satisfied, capability))

    def briefing(self) -> str:
        """The facts as the model is shown them.

        Written as statements of what is true, with the instruction to word them
        rather than judge them. Nothing here is negotiable and nothing here is
        optional to include if the section exists.
        """
        blocks: list[str] = []

        if self.handover is not None:
            return (
                "## Hand this to a person — do not answer the question\n\n"
                f"Subject: {self.handover.name}\n"
                f"Tell the user, in your own words but without softening it: "
                f"{self.handover.reason}\n"
                "Say nothing about the substance of the request, however clear it looks."
            )

        if self.plan.reading:
            blocks.append(
                "## How the request was read\n\n"
                f"{self.plan.reading}\n\n"
                "If a service was inferred rather than named outright, say which one you "
                "answered about so they can correct you."
            )

        if self.scope is not None:
            blocks.append(self._scope_block())

        if self.quote is not None:
            blocks.append(self._quote_block())

        if self.budget is not None:
            blocks.append(self._budget_block())

        if self.listing:
            blocks.append(
                "## The service catalog (complete for what was asked)\n\n"
                f"{self.listing}\n\n"
                "Present this list. Keep every item and its status; you may tidy the "
                "wording around it. Do not add services that are not here."
            )

        if self.capability_summary:
            blocks.append(
                "## What you can do for this person\n\n"
                f"{self.capability_summary}\n\n"
                "Say this naturally, as a colleague explaining what you're useful for."
            )

        if self.roster:
            people = "\n".join(
                f"- {contact.name} — {contact.role.replace('_', ' ')} "
                f"({contact.email}) for {', '.join(contact.countries)}"
                for contact in self.roster
            )
            blocks.append(
                f"## Who owns this\n\n{people}\n\n"
                "Give the name and the role. Include the email only if they asked for it "
                "or need it to act."
            )
        elif self.roster_note:
            blocks.append(f"## Who owns this\n\n{self.roster_note}")

        if self.pending is not None:
            blocks.append(
                "## The next step you are offering\n\n"
                f"{_pending_sentence(self.pending)}\n\n"
                "Offer it as a question and stop there. Nothing is sent until they say yes, "
                "and you must not claim anything has been sent."
            )

        if self.email is not None:
            blocks.append(
                "## Mail\n\n"
                f"{self.audit_outcome or 'email handled'}: "
                f"to {self.email.get('to_name')} <{self.email.get('to')}>, "
                f"subject {self.email.get('subject')!r}.\n\n"
                "Report exactly this outcome. Do not embellish it."
            )

        if self.evidence:
            body = "\n\n---\n\n".join(chunk.content for chunk in self.evidence)
            blocks.append(
                "## Supporting documents\n\n"
                f"{body}\n\n"
                "Use these for detail only. They never override the verdict above."
            )

        if self.notes:
            blocks.append(
                "## Tell the user about this\n\n"
                + "\n".join(f"- {note}" for note in self.notes)
            )

        if not blocks:
            blocks.append(
                "## No facts were found\n\n"
                "Nothing matched this request: no service, no budget line, no list. Say "
                "plainly that you could not tell what they need, ask them to name the "
                "service or the site, and offer to pass it to a person. Do not guess at a "
                "verdict, a price or a budget."
            )

        return "\n\n".join(blocks)

    def _scope_block(self) -> str:
        scope = self.scope
        assert scope is not None

        if scope.outcome is Outcome.AMBIGUOUS:
            options = "\n".join(
                f"{number}. {item.display_name}"
                for number, item in enumerate(scope.items, start=1)
            )
            return (
                "## No verdict — you must ask\n\n"
                f"These could all match, and they are NOT handled the same way:\n{options}\n\n"
                "Ask which one they mean, listing them. State no verdict for any of them and "
                "hint at none: guessing here is what tells someone a chargeable job is free."
            )

        if scope.outcome is Outcome.UNKNOWN or not scope.decided:
            return (
                "## No verdict — nothing matched\n\n"
                "No service in the breakdown matched this request. Say you could not tell "
                "which service is meant, ask them to describe it differently, and offer to "
                "pass it to a person. Do not guess at a verdict or a cost."
            )

        item = scope.candidates[0].item
        status = scope.status
        assert status is not None
        header = (
            "## Verdict (looked up — this is fact, not a suggestion)\n\n"
            f"Service: {item.display_name}\n"
            f"Status: {item.status_raw.strip()} — {item.status_meaning}\n"
            # The internal name, stated so that a reply required to declare the
            # verdict can copy it rather than translate the prose above into a
            # token it was never shown.
            f"Status code: {status.value}\n"
            f"In plain terms: {_STATUS_SENTENCE[status]}\n"
        )
        if scope.outcome is Outcome.AGREED and len(scope.items) > 1:
            also = ", ".join(other.display_name for other in scope.items[1:])
            header += (
                f"\nThe request could also mean {also}, and they all carry this same "
                "status, so the answer is the same either way. Do not ask them to choose.\n"
            )
        return header + (
            "\nSay this outcome in plain language. Do not reinterpret it, do not soften a "
            "no, and do not quote these headings."
        )

    def _quote_block(self) -> str:
        quote = self.quote
        assert quote is not None
        if quote.kind == "variable":
            return (
                "## Price — variable, so there is no automatic figure\n\n"
                f"Tier: {quote.tier or 'Variable'}. This one carries third-party or travel "
                "costs and has to be priced by hand.\n\n"
                "Say there is no standard price and that a person will quote it. Do not "
                "estimate, range or imply a figure."
            )
        if quote.kind == "missing" or quote.price is None:
            return (
                "## Price — not on the rate card\n\n"
                "This is chargeable but has no tier price available.\n\n"
                "Say the price has to come from a person. Invent nothing."
            )
        lines = [
            "## Price (from the rate card — the only figure you may give)\n",
            f"Tier {quote.tier}: {quote.price:,.2f} {quote.currency}",
        ]
        if quote.remaining is not None:
            lines.append(f"Remaining budget at that site: {quote.remaining:,.2f}")
        if quote.over_budget:
            lines.append(
                "This price is ABOVE the remaining budget. Say so clearly and say the extra "
                "funds have to come from the Country Manager."
            )
        lines.append(
            "\nQuote this figure exactly. No other number, no rounding, no ranges."
        )
        return "\n".join(lines)

    def _budget_block(self) -> str:
        budget = self.budget
        assert budget is not None
        if budget.ask_branch and not self.budget_snapshots:
            return (
                "## Budget — which site?\n\n"
                f"{budget.text}\n\n"
                "Ask that question in your own words. Do not invent a figure for a site "
                "you were not given."
            )
        lines = ["## Budget (from the tracker — the only figures you may give)\n"]
        for snapshot in self.budget_snapshots:
            if snapshot.cap is None or snapshot.remaining is None:
                lines.append(
                    f"- {snapshot.branch.name}, fiscal {snapshot.month}: "
                    f"spent {snapshot.spent:,.2f}. The tracker has NO cap for this site "
                    "and month, so the remaining budget is unknown — say so, and do not "
                    "state or imply a balance."
                )
                continue
            lines.append(
                f"- {snapshot.branch.name}, fiscal {snapshot.month}: "
                f"cap {snapshot.cap:,.2f}, spent {snapshot.spent:,.2f}, "
                f"remaining {snapshot.remaining:,.2f}"
            )
        known = [s.remaining for s in self.budget_snapshots if s.remaining is not None]
        if len(self.budget_snapshots) > 1 and known:
            lines.append(f"- Total remaining across those sites: {sum(known):,.2f}")
        lines.append(
            "\nUse these numbers exactly as given. Lead with what they asked for rather "
            "than reciting the whole table, but never change a figure."
        )
        return "\n".join(lines)


def _pending_sentence(pending: PendingAction) -> str:
    if pending.needs_country:
        return (
            "You need their country before you can pick the right person. Ask for it."
        )
    who = {
        "email_am": "their Account Manager",
        "email_cm_po": "their Country Manager, to request a purchase order",
        "email_am_variable": "their Account Manager, to price this by hand",
    }.get(pending.kind, "the right person")
    amount = (
        f" The email would carry the {pending.quote_amount:,.2f} {pending.currency} figure."
        if pending.quote_amount is not None
        else ""
    )
    return f"You can email {who} about this if they confirm.{amount}"
