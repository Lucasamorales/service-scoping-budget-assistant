"""Budget answers from the ledger — wording-ready facts, no LLM required."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import structlog

from app.core.keys import normalize_term
from app.core.money import format_money
from app.store.budget import (
    MONTHS,
    BranchRef,
    BudgetSnapshot,
    BudgetStore,
    canonical_month,
)

__all__ = [
    "BudgetToolResult",
    "answer_budget",
    "country_in_message",
    "month_in_message",
]

logger = structlog.get_logger(__name__)

_MONTH_IN_MESSAGE = re.compile(
    r"\b("
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?"
    r")\b",
    re.IGNORECASE,
)

# "last month", "next fiscal month" — a month named by its distance from the
# one we are in rather than by name. Ordered because "the month" is generic and
# would otherwise swallow the two directional phrases.
#
# These have to be understood rather than merely rejected. The planner emits
# them constantly ("this month" was the slot behind the budget-cap failure),
# and so do people: refusing the phrase would leave the question unanswered
# just as surely as mis-resolving it, only more visibly.
_RELATIVE_MONTHS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"\b(?:next|coming|following)\s+(?:fiscal\s+)?month\b", re.I), 1),
    (re.compile(r"\b(?:last|previous|prior)\s+(?:fiscal\s+)?month\b", re.I), -1),
    (re.compile(r"\b(?:this|current|the)\s+(?:fiscal\s+)?month\b", re.I), 0),
)

# Country / region names people use in chat → Branchescountries.country values.
_COUNTRY_ALIASES: dict[str, str] = {
    "uk": "United Kingdom",
    "u.k": "United Kingdom",
    "u.k.": "United Kingdom",
    "united kingdom": "United Kingdom",
    "britain": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    # Workbook lists the Paris site under country "Paris", not "France".
    "france": "Paris",
    "canada": "Canada",
    "australia": "Australia",
    "paris": "Paris",
}

_ALL_BRANCHES_RE = re.compile(
    r"\b("
    r"all (of )?(the )?(branches|sites|locations|them|those)|"
    r"every (branch|site|location)|"
    r"each (branch|site)|"
    r"the lot|"
    r"across (all )?(the )?(uk|united kingdom|france|canada|australia|branches)"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class BudgetToolResult:
    """Outcome of a budget turn — always safe to show the user."""

    text: str
    snapshot: BudgetSnapshot | None = None
    snapshots: tuple[BudgetSnapshot, ...] = ()
    ask_branch: bool = False
    citations: tuple[str, ...] = ()
    resolved_country: str | None = None
    resolved_branch: str | None = None
    resolved_month: str | None = None
    scope_source: str = "message"
    """``message`` / ``sticky`` / ``session`` — what filled the decisive slot."""


def country_in_message(message: str) -> str | None:
    """The canonical country named in a message, for slot extraction."""
    return _country_from_message(message)


def month_in_message(message: str) -> str | None:
    """The fiscal month label named in a message, for slot extraction."""
    return _month_from_message(message)


def answer_budget(
    message: str,
    store: BudgetStore | None,
    *,
    session_branch: str | None = None,
    session_country: str | None = None,
    sticky_country: str | None = None,
    sticky_branch: str | None = None,
    sticky_month: str | None = None,
    today: date | None = None,
) -> BudgetToolResult:
    """Resolve branch / country / month and format a deterministic budget reply.

    Message slots override sticky slots; sticky fills gaps so follow-ups like
    ``and for the uk?`` or bare ``August`` re-query the ledger without new
    phrasing rules in the router.
    """
    if store is None:
        return BudgetToolResult(
            text=(
                "Budget checks aren't available right now — the tracker isn't loaded. "
                "Your account manager will have the current position."
            )
        )

    when = today or date.today()
    msg_branch = _resolve_branch(message, store, session_branch=None)
    msg_country = _country_from_message(message)
    wants_all = bool(_ALL_BRANCHES_RE.search(message))

    # Every month expression is funnelled through one resolver, and anything it
    # cannot place falls back to the fiscal calendar. The sticky slot is the
    # one that matters: it carries the planner's free text, and before this it
    # reached the caps sheet unchecked. Resolving here rather than at each use
    # also means an unusable month can never be written into session state and
    # poison the rest of the conversation.
    current = store.fiscal_month_for(when)
    month = _month_in(message, current) or _month_in(sticky_month, current) or current
    if sticky_month and _month_in(sticky_month, current) is None:
        logger.info("budget.month_unrecognised", label=sticky_month, using=month)

    # 1) Explicit site this turn (unless they asked for every branch).
    if msg_branch is not None and not wants_all:
        return _single_result(store, msg_branch, month, source="message")

    # 2) Country named this turn → country rollup (clears sticky branch).
    if msg_country is not None:
        return _country_result(store, msg_country, month, source="message")

    # 3) "all of them" → sticky country if we have one, else every branch.
    if wants_all:
        if sticky_country:
            return _country_result(store, sticky_country, month, source="sticky")
        branches = store.branches()
        snapshots = tuple(store.snapshot(branch, month) for branch in branches)
        logger.info(
            "tool.budget",
            country=None,
            branch=None,
            month=month,
            source="message",
            branches=len(snapshots),
        )
        return BudgetToolResult(
            text=_format_rollups("All branches", month, snapshots, group_by_country=True),
            snapshots=snapshots,
            citations=(f"Read from the budget tracker (all branches, {month}).",),
            resolved_country=None,
            resolved_branch=None,
            resolved_month=month,
            scope_source="message",
        )

    # 4) Sticky single branch (e.g. bare "August" after London).
    if sticky_branch:
        found = store.resolve_branch(sticky_branch)
        if found is not None:
            return _single_result(store, found, month, source="sticky")

    # 5) Sticky country rollup.
    if sticky_country:
        return _country_result(store, sticky_country, month, source="sticky")

    # 6) Session defaults.
    session_country_name = _canonical_country(session_country, store)
    if session_country_name is not None and not session_branch:
        return _country_result(store, session_country_name, month, source="session")
    if session_branch:
        found = store.resolve_branch(session_branch)
        if found is not None:
            return _single_result(store, found, month, source="session")

    known = ", ".join(t.name.removeprefix("Acme ").strip() for t in store.branches()[:8])
    more = "…" if len(store.branches()) > 8 else ""
    return BudgetToolResult(
        text=(
            "Which branch should I check? Say the site name "
            f"(for example {known}{more}), or a country "
            "(UK, France, Canada, Australia) for every site there."
        ),
        ask_branch=True,
        resolved_month=month,
        scope_source="none",
    )


def _single_result(
    store: BudgetStore,
    branch: BranchRef,
    month: str,
    *,
    source: str,
) -> BudgetToolResult:
    snapshot = store.snapshot(branch, month)
    logger.info(
        "tool.budget",
        country=branch.country,
        branch=branch.name,
        month=month,
        source=source,
    )
    return BudgetToolResult(
        text=_format_snapshot(snapshot),
        snapshot=snapshot,
        snapshots=(snapshot,),
        citations=(snapshot.citation,),
        resolved_country=branch.country or None,
        resolved_branch=branch.name,
        resolved_month=month,
        scope_source=source,
    )


def _country_result(
    store: BudgetStore,
    country: str,
    month: str,
    *,
    source: str,
) -> BudgetToolResult:
    branches = _branches_for_country(store, country)
    if not branches:
        return BudgetToolResult(
            text=(
                f"I don't have any branches listed under {country} in the budget tracker. "
                "Which site should I check?"
            ),
            ask_branch=True,
            resolved_country=country,
            resolved_month=month,
            scope_source=source,
        )
    snapshots = tuple(store.snapshot(branch, month) for branch in branches)
    logger.info(
        "tool.budget",
        country=country,
        branch=None,
        month=month,
        source=source,
        branches=len(snapshots),
    )
    return BudgetToolResult(
        text=_format_rollups(country, month, snapshots),
        snapshots=snapshots,
        citations=(f"Read from the budget tracker ({country}, {month}).",),
        resolved_country=country,
        resolved_branch=None,
        resolved_month=month,
        scope_source=source,
    )


def _resolve_branch(
    message: str,
    store: BudgetStore,
    session_branch: str | None,
) -> BranchRef | None:
    # Prefer an explicit branch named in the message.
    for branch in store.branches():
        candidates = (
            branch.name,
            branch.location,
            branch.name.removeprefix("Acme ").strip(),
        )
        for candidate in candidates:
            if candidate and re.search(rf"\b{re.escape(candidate)}\b", message, re.I):
                return branch

    if session_branch:
        found = store.resolve_branch(session_branch)
        if found is not None:
            return found
    return None


def _country_from_message(message: str) -> str | None:
    normalized = normalize_term(message)
    # Longest alias first so "united kingdom" wins over bare "kingdom" if added later.
    for alias, country in sorted(_COUNTRY_ALIASES.items(), key=lambda item: -len(item[0])):
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            return country
    return None


def _canonical_country(raw: str | None, store: BudgetStore) -> str | None:
    if not raw or not raw.strip():
        return None
    alias = _COUNTRY_ALIASES.get(normalize_term(raw))
    if alias:
        return alias
    needle = normalize_term(raw)
    for branch in store.branches():
        if normalize_term(branch.country) == needle:
            return branch.country
    return None


def _branches_for_country(store: BudgetStore, country: str) -> tuple[BranchRef, ...]:
    needle = normalize_term(country)
    return tuple(t for t in store.branches() if normalize_term(t.country) == needle)


def _month_from_message(message: str) -> str | None:
    match = _MONTH_IN_MESSAGE.search(message)
    if not match:
        return None
    return canonical_month(match.group(1)) or None


def _relative_offset(label: str) -> int | None:
    """How many months from the current one this phrase means, if any."""
    for pattern, offset in _RELATIVE_MONTHS:
        if pattern.search(label):
            return offset
    return None


def _shift(month: str, offset: int) -> str:
    """Step a fiscal month label, wrapping around the year.

    The caps sheet is twelve columns with no year, so a month is a position in
    a cycle rather than a date. December plus one is January, and that is the
    correct answer for a sheet shaped this way.
    """
    return MONTHS[(MONTHS.index(month) + offset) % len(MONTHS)]


def _month_in(text: str | None, current: str) -> str | None:
    """Turn any month expression into a label the caps sheet actually has.

    Takes either a slot value ("August", "this month") or a whole sentence
    ("what was the london budget in august"), because the two arrive from the
    planner and from the user in the same field and neither is trustworthy.

    Returns ``None`` for anything unrecognisable, so the caller falls back to
    the fiscal calendar rather than querying a column that does not exist.
    This is the boundary the planner's free text crosses: past it, every value
    is a real sheet key, and nothing a model writes can invent one.
    """
    if not text or not text.strip():
        return None
    if exact := canonical_month(text):
        return exact  # the value is a month, exactly
    if mentioned := _month_from_message(text):
        return mentioned  # a month named somewhere inside a sentence
    offset = _relative_offset(text)
    return None if offset is None else _shift(current, offset)


def _format_snapshot(snapshot: BudgetSnapshot) -> str:
    site = snapshot.branch.name
    lines = [
        f"**{site}** — fiscal **{snapshot.month}**",
        f"- Cap: {format_money(snapshot.cap)}",
        f"- Spent: {format_money(snapshot.spent)}",
        f"- Remaining: {format_money(snapshot.remaining)}",
    ]
    if not snapshot.cap_known:
        lines.append(
            "- The tracker has no cap for this site and month, so I can't say what is "
            "left. Spend above is what has been logged."
        )
    if snapshot.lines:
        recent = sorted(
            snapshot.lines,
            key=lambda line: line.po_date or date.min,
            reverse=True,
        )[:3]
        detail = "; ".join(
            f"{line.media_type or 'Spend'} {format_money(line.amount)}"
            + (f" ({line.description})" if line.description else "")
            for line in recent
        )
        lines.append(f"- Recent lines: {detail}")
    else:
        lines.append("- No spend logged for this month yet.")
    return "\n".join(lines)


def _format_rollups(
    title: str,
    month: str,
    snapshots: tuple[BudgetSnapshot, ...],
    *,
    group_by_country: bool = False,
) -> str:
    if not snapshots:
        return f"No branches found for **{title}** in the budget tracker."

    # Totals cover only the sites the sheet actually caps. Folding an unknown
    # cap in as zero understated the rollup and made the gap invisible.
    capped = tuple(s for s in snapshots if s.cap_known)
    uncapped = len(snapshots) - len(capped)
    total_cap = round(sum(s.cap or 0.0 for s in capped), 2)
    total_spent = round(sum(s.spent for s in snapshots), 2)
    total_remaining = round(sum(s.remaining or 0.0 for s in capped), 2)
    lines = [
        f"**{title}** — fiscal **{month}** ({len(snapshots)} branches)",
        f"- Cap: {format_money(total_cap)}",
        f"- Spent: {format_money(total_spent)}",
        f"- Remaining: {format_money(total_remaining)}",
    ]
    if uncapped:
        lines.append(
            f"- Excludes {uncapped} site(s) with no cap in the tracker for {month}."
        )
    lines.append("")

    if group_by_country:
        by_country: dict[str, list[BudgetSnapshot]] = {}
        for snap in snapshots:
            by_country.setdefault(snap.branch.country or "Other", []).append(snap)
        for country in sorted(by_country):
            lines.append(f"**{country}**")
            for snap in by_country[country]:
                lines.append(_rollup_line(snap))
            lines.append("")
        if lines[-1] == "":
            lines.pop()
    else:
        for snap in snapshots:
            lines.append(_rollup_line(snap))

    return "\n".join(lines)


def _rollup_line(snapshot: BudgetSnapshot) -> str:
    site = snapshot.branch.name.removeprefix("Acme ").strip() or snapshot.branch.name
    return (
        f"- **{site}**: remaining {format_money(snapshot.remaining)} "
        f"(cap {format_money(snapshot.cap)} / spent {format_money(snapshot.spent)})"
    )
