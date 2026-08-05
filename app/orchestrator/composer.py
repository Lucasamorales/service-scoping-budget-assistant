"""Writing the answer without a model.

The verdict is read from the catalog, not generated, so a correct reply can be
assembled from it directly. That makes the language model a genuine
enhancement - better wording, handling of odd phrasing, follow-up conversation
- rather than a dependency the answer rests on.

Two things follow, and both matter more than the prose quality here:

The assistant keeps working when Vertex AI is unreachable, rate limited, or
simply not configured yet. It gets terser, not wrong.

Every path through the system can be tested end to end with no credentials and
no network, which is why the whole eval suite runs in about a second.

The wording is deliberately plain. It is a fallback, and sounding polished
would only make it harder to tell which one produced a given reply.
"""

from __future__ import annotations

from app.core.types import Status
from app.knowledge.retriever import RetrievalResult
from app.orchestrator.resolver import Outcome, Resolution
from app.orchestrator.router import Intent, Route

__all__ = ["compose"]

# What each verdict means for the person asking, in the second person. The
# corpus supplies its own wording for the verdict itself; this is the practical
# consequence, which the documents state per item but not in a reusable form.
_NEXT_STEP: dict[Status, str] = {
    Status.IN_SCOPE: "Central marketing covers this, so raise it with your account manager.",
    Status.OUT_OF_SCOPE: "Central marketing cannot take this on.",
    Status.LOCAL: "This one sits with your own site and operations team rather than central "
    "marketing.",
    Status.QUOTE_REQUIRED: "This can be done, but it needs quoting before it goes ahead.",
}

_CAPABILITIES = (
    "I can tell you whether a marketing request is covered by central marketing, refused, "
    "handled by your local team, or something that needs quoting first. Ask me about a "
    "service and I will give you the verdict from Acme's service breakdown."
)

_GREETING = "Ask me whether a marketing request is in scope and I will look it up."

_NO_SERVICE = (
    "I could not tell which service you mean, so I would rather not guess. Try describing it "
    "differently, or I can pass this to a person."
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
        return (
            "I cannot check budgets yet - the spreadsheet is not connected. Ask your account "
            "manager for the current position."
        )

    if route.intent is Intent.QUOTE:
        return (
            "I cannot produce a quote. If the service needs one, your account manager will "
            "arrange it. Tell me which service you mean and I will confirm whether it is in "
            "scope."
        )

    if route.intent is Intent.ACTION:
        return (
            "I cannot send anything yet. Tell me which service this is about and I will "
            "confirm whether it is in scope, then you can pass that on."
        )

    return _scope_answer(resolution, retrieval)


def _scope_answer(resolution: Resolution, retrieval: RetrievalResult) -> str:
    if resolution.outcome is Outcome.UNKNOWN:
        return _NO_SERVICE

    if resolution.outcome is Outcome.AMBIGUOUS:
        # Deliberately states no verdict, not even a hint of one. These
        # candidates disagree about scope, so any hint would be a coin toss
        # dressed up as an answer.
        return resolution.question() or _NO_SERVICE

    status = resolution.status
    meaning = resolution.status_meaning
    if status is None or meaning is None:
        return _NO_SERVICE

    lines: list[str] = []

    if resolution.outcome is Outcome.RESOLVED:
        item = resolution.candidates[0].item
        lines.append(f"**{item.display_name}** — {meaning}.")
    else:
        names = " or ".join(item.display_name for item in resolution.items)
        lines.append(f"Whether you mean {names}, the answer is the same: {meaning}.")

    lines.append(_NEXT_STEP[status])

    if detail := _detail_for(resolution):
        lines.append(detail)

    lines.append(f"_{retrieval.citation_line()}_")
    return "\n\n".join(lines)


def _detail_for(resolution: Resolution) -> str | None:
    """Pull the corpus's own explanation, if the document carries one.

    Quoted rather than paraphrased. The whole point of the catalog is that it
    is the single source of truth for how a verdict is described, and a
    fallback path is the last place that should start rewording it.
    """
    if resolution.outcome is not Outcome.RESOLVED:
        return None

    item = resolution.candidates[0].item
    if glance := item.at_a_glance.how_to_get_it:
        return glance
    return item.summary or None
