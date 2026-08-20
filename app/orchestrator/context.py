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

from app.core.errors import CatalogError
from app.core.types import Chunk, DocType
from app.knowledge.manifest import Manifest
from app.knowledge.retriever import RetrievalResult
from app.orchestrator.history import HistoryTurn, format_history
from app.orchestrator.resolver import Outcome, Resolution
from app.orchestrator.router import Route

__all__ = [
    "EVIDENCE_TOKEN_BUDGET",
    "ContextPack",
    "HistoryTurn",
    "build_context",
    "load_system_prompt",
]

logger = structlog.get_logger(__name__)

DEFAULT_PROMPT_PATH = Path("prompts/system.md")
DEFAULT_DOCUMENTS_DIR = Path("documents")

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
def load_system_prompt(
    path: Path = DEFAULT_PROMPT_PATH,
    documents_dir: Path = DEFAULT_DOCUMENTS_DIR,
) -> str:
    """Read the always-on instructions, plus any meta corpus documents.

    ``prompts/system.md`` holds the rules. Meta documents (tone of voice, and
    later anything else that should shape wording but never be cited as
    evidence) are appended so marketing can edit the brand voice without
    touching the safety rules.
    """
    try:
        base = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        # Falling back to nothing would leave a model with no instructions at
        # all, which is far more dangerous than refusing to answer.
        logger.error("prompt.unreadable", path=str(path), error=str(exc))
        raise

    extras = _load_meta_documents(documents_dir)
    if not extras:
        return base
    return f"{base}\n\n---\n\n{extras}"


def _load_meta_documents(documents_dir: Path) -> str:
    try:
        manifest = Manifest.load(documents_dir)
    except (CatalogError, OSError, ValueError) as exc:
        logger.warning("prompt.meta_unavailable", error=str(exc))
        return ""

    sections: list[str] = []
    for entry in manifest.of_type(DocType.META):
        path = entry.path_in(documents_dir)
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("prompt.meta_unreadable", path=str(path), error=str(exc))
            continue
        if text:
            sections.append(f"# Brand reference — {entry.file}\n\n{text}")

    return "\n\n".join(sections)


@dataclass(frozen=True, slots=True)
class ContextPack:
    """Everything the model is given for one turn, and an account of it."""

    system_prompt: str
    verdict_block: str
    evidence: tuple[Chunk, ...]
    citations: tuple[str, ...]
    question: str = ""
    """The user's message. Must appear in the user turn — without it the model
    only sees instructions and invents a greeting instead of answering."""

    history: tuple[HistoryTurn, ...] = ()
    """Prior turns for continuity. Wording only — never overrides the scope fact."""

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

    def user_turn(self) -> str:
        """What the model sees as the user message for this turn.

        Verdict and evidence sit here with the question so a single-blob
        ``contents=`` call still answers. Prefer pairing this with
        ``system_prompt`` as ``system_instruction`` when the SDK allows it.
        """
        sections = [
            self.verdict_block,
            "## Supporting documents\n\n" + self.evidence_text(),
        ]
        if self.notes:
            sections.append(
                "## Tell the user about this\n\n"
                + "\n".join(f"- {note}" for note in self.notes)
            )
        if self.history:
            sections.append(
                "## Recent conversation\n\n"
                "Prior turns for continuity only. Do not re-litigate earlier scope "
                "calls from this transcript — the scope fact for *this* turn above "
                "is authoritative.\n\n"
                + format_history(self.history)
            )
        sections.append(f"## User question\n\n{self.question}")
        return "\n\n".join(sections)

    def as_prompt(self) -> str:
        """Full text for debugging / ``scripts.ask --prompt``."""
        return f"{self.system_prompt}\n\n{self.user_turn()}"


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
            "## Scope fact (internal — never quote this heading)\n\n"
            f"Service: {item.display_name}\n"
            f"Status: {item.status_raw.strip()} — {item.status_meaning}\n\n"
            "Tell the user this outcome in plain language. Do not reinterpret it. "
            "Do not paste this heading or the words 'authoritative verdict'. "
            "If a recent conversation is attached, use it for continuity only."
        )

    if resolution.outcome is Outcome.AGREED:
        options = "\n".join(f"- {item.display_name}" for item in resolution.items)
        first = resolution.candidates[0].item
        return (
            "## Scope fact (internal — never quote this heading)\n\n"
            f"The request could mean any of these:\n{options}\n\n"
            f"They all carry the same status: {first.status_raw.strip()} — "
            f"{first.status_meaning}\n\n"
            "So the answer is the same either way. Give the outcome in plain language, mention "
            "that it covers all of the above, and do not ask the user to choose between them. "
            "Do not paste this heading. Recent conversation is continuity only."
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
    question: str = "",
    history: tuple[HistoryTurn, ...] = (),
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
        question=question or route.message,
        history=history,
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
