"""Catalog overview answers — services come from the loaded corpus, not retrieval.

Recognising *that* the user wants this overview can be semantic (embeddings).
Producing the overview itself is always a full catalog dump: RAG top-k cannot
honestly list every service.
"""

from __future__ import annotations

import re
from collections import defaultdict

from app.core.keys import normalize_term
from app.core.types import ServiceItem, Status
from app.knowledge.catalog import ServiceCatalog

__all__ = [
    "list_services",
    "section_in_message",
    "status_filter_in_message",
    "wants_service_list",
]

_STATUS_LABEL = {
    Status.IN_SCOPE: "in scope",
    Status.QUOTE_REQUIRED: "on demand",
    Status.LOCAL: "local",
    Status.OUT_OF_SCOPE: "out of scope",
}

# Cheap, obvious inventory asks. Paraphrases are handled by InventoryIntentDetector.
_LIST_RE = re.compile(
    r"\b("
    r"what (are|is) (our|the|your)?\s*services|"
    r"which services|"
    r"(list|show|tell me|give me).{0,24}\b(services|offerings|catalogue|catalog)\b|"
    r"(a |the )?(full )?list of .{0,20}\bservices\b|"
    r"full (service )?list|"
    r"service (list|catalogue|catalog|breakdown)|"
    r"(on[- ]demand|in[- ]scope|local|out of scope)\s+services|"
    r"services\s+(that are |which are )?(on[- ]demand|in[- ]scope|local|out of scope)"
    r")\b",
    re.IGNORECASE,
)

_ON_DEMAND_RE = re.compile(
    r"\b(on[- ]demand|on demand|quote required|need(s)? a quote)\b",
    re.IGNORECASE,
)
_PAID_RE = re.compile(
    r"\b(chargeable|cost money|paid for|on[- ]demand|on demand)\b",
    re.IGNORECASE,
)
_IN_SCOPE_RE = re.compile(
    # Bare "free" counts: "what do I get for free" is the same question as
    # "which services are in scope", phrased the way people actually ask it.
    r"\b(in[- ]scope|included|free of charge|free|foc|no cost|at no charge)\b",
    re.IGNORECASE,
)
_LOCAL_RE = re.compile(r"\b(local(ly)?)\b", re.IGNORECASE)
_OUT_RE = re.compile(r"\b(out of scope|out-of-scope|not (in )?scope)\b", re.IGNORECASE)


def wants_service_list(message: str) -> bool:
    """True for inventory questions (full list or filtered by status/section)."""
    if _LIST_RE.search(message):
        return True
    # "on demand services" / "services that are local" without other list verbs
    return bool(
        re.search(r"\bservices?\b", message, re.IGNORECASE) and _status_filter(message)
    )


def status_filter_in_message(message: str) -> Status | None:
    """The status a message asks to filter by, for slot extraction."""
    return _status_filter(message)


def section_in_message(catalog: ServiceCatalog, message: str) -> str | None:
    """The catalog section a message names, for slot extraction."""
    return _section_mentioned(catalog, message)


def list_services(
    catalog: ServiceCatalog,
    message: str = "",
    *,
    section: str | None = None,
    status: Status | None = None,
) -> str:
    """Format the real catalog, optionally filtered by section and/or status.

    Filters are read from the message unless the caller passes them, which is
    how a planned turn narrows the list without the wording having to contain
    the words a regex would look for.
    """
    section_filter = section or _section_mentioned(catalog, message)
    status_filter = status if status is not None else _status_filter(message)

    by_section: dict[str, list[ServiceItem]] = defaultdict(list)
    for item in catalog:
        if section_filter and normalize_term(item.section) != normalize_term(section_filter):
            continue
        if status_filter is not None and item.status is not status_filter:
            continue
        by_section[item.section].append(item)

    if not by_section:
        if status_filter is not None:
            label = _STATUS_LABEL[status_filter]
            return (
                f"I don’t have any **{label}** services in that slice. "
                "Try the full list, or another filter."
            )
        return (
            "I couldn’t match that to a section. "
            "Ask for the full list, or name a category like Events or Photography."
        )

    for items in by_section.values():
        items.sort(key=lambda item: item.item.lower())

    total = sum(len(v) for v in by_section.values())
    parts: list[str] = []
    if status_filter is not None and section_filter:
        parts.append(
            f"**{section_filter}** — **{_STATUS_LABEL[status_filter]}** ({total}):"
        )
    elif status_filter is not None:
        parts.append(f"**{_STATUS_LABEL[status_filter].title()}** services ({total}):")
    elif section_filter:
        parts.append(f"Under **{section_filter}**:")
    else:
        parts.append("Here’s what central marketing covers, by area:")

    for section in sorted(by_section):
        if status_filter is not None:
            lines = [f"- {item.item}" for item in by_section[section]]
        else:
            lines = [
                f"- {item.item} — {_STATUS_LABEL[item.status]}"
                for item in by_section[section]
            ]
        parts.append(f"**{section}**\n" + "\n".join(lines))

    parts.append("Want the detail on one of these? Just ask — e.g. “can we do merch?”")
    return "\n\n".join(parts)


def _status_filter(message: str) -> Status | None:
    # Asking for both sides of the ledger is a full list with labels, not a
    # filter: "which things are free and which cost money".
    if _IN_SCOPE_RE.search(message) and _PAID_RE.search(message):
        return None
    # Out-of-scope before bare "scope"; on-demand before generic "quote".
    if _OUT_RE.search(message):
        return Status.OUT_OF_SCOPE
    if _ON_DEMAND_RE.search(message):
        return Status.QUOTE_REQUIRED
    if _IN_SCOPE_RE.search(message):
        return Status.IN_SCOPE
    if _LOCAL_RE.search(message) and re.search(r"\bservices?\b", message, re.I):
        return Status.LOCAL
    return None


def _section_mentioned(catalog: ServiceCatalog, message: str) -> str | None:
    if not message.strip():
        return None
    normalized = normalize_term(message)
    sections = sorted(catalog.sections(), key=len, reverse=True)
    for section in sections:
        if normalize_term(section) in normalized:
            return section
    return None
