"""Assembling what the model is actually shown.

Everything upstream produces facts. This turns them into a prompt without
letting any of them become negotiable.

The important piece is the verdict block. Rather than dropping the documents in
and hoping the model reads the status correctly, the verdict arrives as a
separate, explicit statement of what the model is permitted to say - including,
when the resolver could not decide, an instruction that it has no verdict and
must ask. The model's job is wording, not adjudication.

Two smaller rules earn their place:

**Trimming is never silent.** When evidence does not fit the budget, the pack
says what was dropped and the prompt tells the model to mention it. An answer
based on partial material that presents itself as complete is worse than a
short answer.

**Citations always exist.** Even "no supporting documents were retrieved" is a
citation, because the alternative is an answer whose basis nobody can check.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import structlog

from app.core.types import Chunk
from app.knowledge.retriever import RetrievalResult
from app.orchestrator.resolver import Outcome, Resolution
from app.orchestrator.router import Route

__all__ = [
    "EVIDENCE_TOKEN_BUDGET",
    "ContextPack",
    "build_context",
    "load_system_prompt",
]

logger = structlog.get_logger(__name__)

DEFAULT_PROMPT_PATH = Path("prompts/system.md")

EVIDENCE_TOKEN_BUDGET = 3000
"""Tokens allowed for retrieved documents, excluding the prompt and the verdict.

Roughly six whole service documents. Generous for a corpus whose largest
document is 2,000 characters, and the ceiling exists to bound cost and latency
rather than because the model could not hold more."""

CHARACTERS_PER_TOKEN = 4
"""Rough conversion, good to about ten percent for English prose. Used for
budgeting only, never for billing, so an approximation is fine and avoids a
tokeniser dependency in the request path."""


def estimate_tokens(text: str) -> int:
    return len(text) // CHARACTERS_PER_TOKEN


@lru_cache(maxsize=1)
def load_system_prompt(path: Path = DEFAULT_PROMPT_PATH) -> str:
    """Read the always-on instructions.

    Kept as a document rather than a string in code so the people who own how
    Acme talks to its own staff can edit it without a deployment.
    """
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        # Falling back to nothing would leave a model with no instructions at
        # all, which is far more dangerous than refusing to answer.
        logger.error("prompt.unreadable", path=str(path), error=str(exc))
        raise


@dataclass(frozen=True, slots=True)
class ContextPack:
    """Everything the model is given for one turn, and an account of it."""

    system_prompt: str
    verdict_block: str
    evidence: tuple[Chunk, ...]
    citations: tuple[str, ...]
    notes: tuple[str, ...] = ()
    """Anything the answer should acknowledge: trimmed material, degraded
    retrieval, missing documents."""

    dropped: tuple[str, ...] = ()

    @property
    def estimated_tokens(self) -> int:
        return estimate_tokens(self.as_prompt())

    def evidence_text(self) -> str:
        if not self.evidence:
            return "No supporting documents were retrieved for this request."
        return "\n\n---\n\n".join(chunk.content for chunk in self.evidence)

    def as_prompt(self) -> str:
        """The full turn, in the order the model should read it.

        The verdict comes before the evidence deliberately. It is the
        conclusion; the documents are only there to explain it.
        """
        sections = [
            self.system_prompt,
            self.verdict_block,
            "## Supporting documents\n\n" + self.evidence_text(),
        ]
        if self.notes:
            sections.append(
                "## Tell the user about this\n\n"
                + "\n".join(f"- {note}" for note in self.notes)
            )
        return "\n\n".join(sections)


def _verdict_block(resolution: Resolution, route: Route) -> str:
    """State what the model is allowed to say about scope."""
    if route.handover_topic is not None:
        return (
            "## HANDOVER — do not answer the underlying question\n\n"
            f"This request is about {route.handover_topic.name}. "
            f"Tell the user: {route.handover_topic.reason}\n"
            "Offer nothing else. Do not comment on the substance, however clear it seems."
        )

    if resolution.outcome is Outcome.RESOLVED:
        item = resolution.candidates[0].item
        return (
            "## AUTHORITATIVE VERDICT — read from the service breakdown\n\n"
            f"Service: {item.display_name}\n"
            f"Verdict: {item.status_raw.strip()} — {item.status_meaning}\n\n"
            "State this verdict using that wording. Do not reinterpret it."
        )

    if resolution.outcome is Outcome.AGREED:
        options = "\n".join(f"- {item.display_name}" for item in resolution.items)
        first = resolution.candidates[0].item
        return (
            "## AUTHORITATIVE VERDICT — read from the service breakdown\n\n"
            f"The request could mean any of these:\n{options}\n\n"
            f"They all carry the same verdict: {first.status_raw.strip()} — "
            f"{first.status_meaning}\n\n"
            "So the answer is the same either way. Give the verdict, mention that it covers "
            "all of the above, and do not ask the user to choose between them."
        )

    if resolution.outcome is Outcome.AMBIGUOUS:
        options = "\n".join(
            f"{number}. {item.display_name}"
            for number, item in enumerate(resolution.items, start=1)
        )
        return (
            "## NO VERDICT — you must ask\n\n"
            f"These services could all match, and they are NOT handled the same way:\n{options}\n\n"
            "Ask which one is meant, listing them. Do not state a verdict for any of them, "
            "and do not hint at one. Guessing here gives the wrong answer about cost."
        )

    return (
        "## NO VERDICT — nothing matched\n\n"
        "No service in the breakdown matched this request. Say you could not tell which "
        "service is meant, ask them to describe it differently, and offer to pass it to a "
        "person. Do not guess at a verdict or a cost."
    )


def _citations(retrieval: RetrievalResult, evidence: tuple[Chunk, ...]) -> tuple[str, ...]:
    if not evidence:
        return ("No supporting documents retrieved.",)
    forced = {hit.chunk.chunk_id for hit in retrieval.hits if hit.forced}
    return tuple(
        f"{chunk.section_title or chunk.source}"
        + (" (required by the resolver)" if chunk.chunk_id in forced else "")
        for chunk in evidence
    )


def _fit_to_budget(
    retrieval: RetrievalResult, budget: int
) -> tuple[tuple[Chunk, ...], tuple[str, ...]]:
    """Take as much evidence as fits, keeping the most important first.

    Forced slices survive trimming: the resolver required them because the
    request is about them, so dropping one leaves an answer about the wrong
    thing. They are ordered first by the retriever, so taking in order is
    enough.
    """
    kept: list[Chunk] = []
    dropped: list[str] = []
    used = 0

    for hit in retrieval.hits:
        cost = estimate_tokens(hit.chunk.content)
        if used + cost > budget and kept:
            dropped.append(hit.chunk.section_title or hit.chunk.source)
            continue
        kept.append(hit.chunk)
        used += cost

    return tuple(kept), tuple(dropped)


def build_context(
    route: Route,
    resolution: Resolution,
    retrieval: RetrievalResult,
    *,
    system_prompt: str | None = None,
    budget: int = EVIDENCE_TOKEN_BUDGET,
) -> ContextPack:
    """Assemble one turn's prompt from the decisions already made."""
    evidence, dropped = _fit_to_budget(retrieval, budget)
    notes: list[str] = []

    if dropped:
        notes.append(
            f"Only part of the supporting material fitted, so {len(dropped)} document(s) "
            f"were left out ({', '.join(dropped)}). Say the answer may be incomplete."
        )

    if resolution.outcome is not Outcome.UNKNOWN and not evidence:
        notes.append(
            "The verdict above is reliable, but no supporting text was retrieved to explain "
            "it. Give the verdict and say you have no further detail."
        )

    for note in retrieval.notes:
        logger.info("context.retrieval_note", note=note)

    pack = ContextPack(
        system_prompt=system_prompt if system_prompt is not None else load_system_prompt(),
        verdict_block=_verdict_block(resolution, route),
        evidence=evidence,
        citations=_citations(retrieval, evidence),
        notes=tuple(notes),
        dropped=dropped,
    )

    logger.info(
        "context.built",
        intent=route.intent.value,
        outcome=resolution.outcome.value,
        evidence=len(evidence),
        dropped=len(dropped),
        tokens=pack.estimated_tokens,
    )
    return pack
