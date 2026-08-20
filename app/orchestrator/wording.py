"""Saying the facts out loud.

This is the only place a model writes something a user reads, and it runs after
every decision has been made. It is handed a :class:`~app.orchestrator.facts.FactPack`
and a question, and its output is checked by :mod:`app.orchestrator.guard`
before anybody sees it.

Three outcomes, and all three are answers:

- the model wrote something the facts support, and that is used;
- the model failed, returned nothing, or broke a guard, so the deterministic
  wording is used and the turn is marked degraded;
- there was no model to begin with, so the deterministic wording is used and
  nothing is marked at all, because that is not a fault.

Streaming is a special case worth being explicit about. Once a fragment has
been sent it cannot be recalled, so a guard violation part-way through cannot be
repaired — which is why generation is buffered on turns that carry a figure or a
verdict, and only streamed when there is nothing to contradict.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import structlog

from app.orchestrator.facts import FactPack
from app.orchestrator.guard import inspect
from app.orchestrator.history import HistoryTurn, format_history
from app.orchestrator.llm import DETERMINISTIC, LanguageModel, ModelUnavailableError

__all__ = ["Worded", "build_briefing", "stream_wording", "word_answer"]

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Worded:
    text: str
    source: str
    degraded: bool = False
    """The model was meant to write this and could not, or wrote something the
    facts did not support. Surfaced so an outage looks like an outage."""

    truncated: bool = False
    """Text was already on the wire when the model died. The caller must keep
    what arrived; it cannot be replaced with the fallback."""


def build_briefing(
    facts: FactPack,
    question: str,
    history: tuple[HistoryTurn, ...] = (),
) -> str:
    """The user turn sent to the model: the facts, the thread, the question."""
    sections = [
        "# Briefing for this turn\n\n"
        "Everything below was looked up by the backend for this message. Word it for the "
        "person asking. Do not add facts, figures or verdicts that are not here, and do "
        "not quote these headings.",
        facts.briefing(),
    ]
    if history:
        sections.append(
            "## Recent conversation\n\n"
            "Continuity only. Do not re-decide anything settled above.\n\n"
            + format_history(history)
        )
    sections.append(f"## Their message\n\n{question}")
    return "\n\n".join(sections)


def word_answer(
    model: LanguageModel | None,
    facts: FactPack,
    question: str,
    history: tuple[HistoryTurn, ...] = (),
    *,
    system_prompt: str | None = None,
) -> Worded:
    """Ask the model to word the facts, and fall back without ceremony."""
    if model is None or not facts.allows_generation:
        return Worded(facts.fallback_text, DETERMINISTIC)

    briefing = build_briefing(facts, question, history)
    try:
        reply = model.generate(briefing, system_instruction=system_prompt)
    except ModelUnavailableError as exc:
        logger.warning("wording.model_unavailable", error=str(exc))
        return Worded(facts.fallback_text, DETERMINISTIC, degraded=True)

    text = reply.text.strip()
    if not text:
        logger.warning("wording.empty", model=reply.model)
        return Worded(facts.fallback_text, DETERMINISTIC, degraded=True)

    if violation := inspect(text, facts):
        logger.error(
            "wording.guard_violation",
            model=reply.model,
            kind=violation.kind,
            detail=violation.detail,
        )
        return Worded(facts.fallback_text, DETERMINISTIC, degraded=True)

    return Worded(text, reply.model)


def stream_wording(
    model: LanguageModel | None,
    facts: FactPack,
    question: str,
    history: tuple[HistoryTurn, ...] = (),
    *,
    system_prompt: str | None = None,
) -> Iterator[str | Worded]:
    """Yield fragments as they arrive, then one :class:`Worded` summarising it.

    Turns carrying a figure or a verdict are generated whole and yielded in one
    piece: a guarded answer cannot be un-sent halfway through, and a correct
    slow answer beats a fast retraction.
    """
    if model is None or not facts.allows_generation:
        yield facts.fallback_text
        yield Worded(facts.fallback_text, DETERMINISTIC)
        return

    if _must_be_checked(facts):
        worded = word_answer(
            model, facts, question, history, system_prompt=system_prompt
        )
        yield worded.text
        yield worded
        return

    briefing = build_briefing(facts, question, history)
    pieces: list[str] = []
    try:
        for piece in model.stream(briefing, system_instruction=system_prompt):
            pieces.append(piece)
            yield piece
    except ModelUnavailableError as exc:
        if not pieces:
            logger.warning("wording.stream_degraded", error=str(exc))
            yield facts.fallback_text
            yield Worded(facts.fallback_text, DETERMINISTIC, degraded=True)
            return
        logger.error("wording.stream_truncated", error=str(exc), emitted=len(pieces))
        yield Worded("".join(pieces), model.name, degraded=True, truncated=True)
        return

    text = "".join(pieces).strip()
    if not text:
        logger.warning("wording.stream_empty", model=model.name)
        yield facts.fallback_text
        yield Worded(facts.fallback_text, DETERMINISTIC, degraded=True)
        return
    yield Worded(text, model.name)


def _must_be_checked(facts: FactPack) -> bool:
    """Whether this turn's wording has to be verified before it is shown."""
    return (
        facts.verdict is not None
        or facts.quote is not None
        or facts.budget is not None
        or facts.email is not None
    )
