"""Writing the answer without a model.

The verdict is read from the catalog, not generated, so a correct reply can be
assembled from it directly. That makes the language model a genuine
enhancement - better wording, conversation, brand voice - rather than a
dependency the answer rests on.

When Gemini is available it should carry the Acme tone. This composer is the
fallback: warmer than a form, still plain enough that you can tell which path
answered. It gets terser when the model is down, not wrong.
"""

from __future__ import annotations

from app.core.types import Status
from app.knowledge.retriever import RetrievalResult
from app.orchestrator.resolver import Outcome, Resolution
from app.orchestrator.router import Intent, Route

__all__ = ["compose"]

_NEXT_STEP: dict[Status, str] = {
    Status.IN_SCOPE: "Central marketing covers this — I can ping your Account Manager when you're ready.",
    Status.OUT_OF_SCOPE: "Central marketing can't take this one on.",
    Status.LOCAL: "That one's on your local site / ops team, not central marketing.",
    Status.QUOTE_REQUIRED: "We can do it on demand — it'll need a quote before it goes ahead.",
}

_CAPABILITIES = (
    "I can tell you whether a marketing request is covered by central marketing, sits with "
    "your local team, is out of scope, or needs quoting first — and I can check a branch's "
    "remaining budget for the current fiscal month. Ask me to **list the services** for the "
    "full breakdown from the catalog, or name a request (e.g. merch, billboards)."
)

_GREETING = (
    "Hey — ask me about a marketing request and I'll tell you if it's in scope, local, "
    "out of scope, or needs a quote."
)

_NO_SERVICE = (
    "I don't have that capability — this assistant only covers central marketing "
    "scope, budget checks, and quotes. Try describing a marketing request, or ask "
    "what services we cover."
)


def compose(route: Route, resolution: Resolution, retrieval: RetrievalResult) -> str:
    """Build a reply from the decisions already made."""
    if route.intent is Intent.HANDOVER and route.handover_topic is not None:
        return route.handover_topic.reason

    if route.intent is Intent.CAPABILITIES:
        return _CAPABILITIES

    if route.intent is Intent.GREETING:
        return _GREETING

    if route.intent is Intent.BUDGET:
        # Prefer app.tools.budget via the pipeline. This branch is only reached
        # if something called compose directly without the tool.
        return (
            "Budget checks aren't available right now — the tracker isn't loaded. "
            "Your account manager will have the current position."
        )

    if route.intent is Intent.QUOTE:
        return (
            "I can't produce a quote from here. Tell me which service you mean and I'll "
            "confirm whether it's in scope or needs quoting — your AM can take it from there."
        )

    if route.intent is Intent.ACTION:
        return (
            "I can't send anything yet. Tell me which service this is about, I'll confirm "
            "the scope, and you can pass that on."
        )

    return _scope_answer(resolution, retrieval)


def _scope_answer(resolution: Resolution, retrieval: RetrievalResult) -> str:
    if resolution.outcome is Outcome.UNKNOWN:
        return _NO_SERVICE

    if resolution.outcome is Outcome.AMBIGUOUS:
        return resolution.question() or _NO_SERVICE

    status = resolution.status
    meaning = resolution.status_meaning
    if status is None or meaning is None:
        return _NO_SERVICE

    if resolution.outcome is Outcome.RESOLVED:
        item = resolution.candidates[0].item
        head = f"For **{item.display_name}**: {meaning}"
    else:
        names = " or ".join(item.display_name for item in resolution.items)
        head = f"Whether you mean {names}, same answer: {meaning}"

    parts = [head, _NEXT_STEP[status]]
    if detail := _detail_for(resolution):
        parts.append(detail)
    parts.append(f"_(From {retrieval.citation_line().removeprefix('Read from ').rstrip('.')})_")
    return "\n\n".join(parts)


def _detail_for(resolution: Resolution) -> str | None:
    if resolution.outcome is not Outcome.RESOLVED:
        return None

    item = resolution.candidates[0].item
    if glance := item.at_a_glance.how_to_get_it:
        return glance
    return item.summary or None
