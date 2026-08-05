"""One turn, start to finish.

Route, resolve, retrieve, assemble, and only then generate. Each step narrows
what the next is allowed to do, and by the time the model is called every
decision that affects correctness has already been made.

The model is optional throughout. When it is absent, unreachable or slow, the
turn completes from :mod:`app.orchestrator.composer` using the same facts, and
the answer says so. Nothing about the verdict changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from app.core.config import Settings, get_settings
from app.core.types import Status
from app.knowledge.catalog import ServiceCatalog, load_catalog
from app.knowledge.index import KnowledgeIndex
from app.knowledge.manifest import Manifest
from app.knowledge.retriever import InMemoryRetriever, RetrievalResult
from app.orchestrator.composer import compose
from app.orchestrator.context import ContextPack, build_context, load_system_prompt
from app.orchestrator.llm import DETERMINISTIC, LanguageModel, build_model
from app.orchestrator.resolver import Outcome, Resolution, ScopeResolver
from app.orchestrator.router import ConversationState, Intent, Route, Router

__all__ = ["Answer", "Pipeline"]

logger = structlog.get_logger(__name__)

EVIDENCE_LIMIT = 4


@dataclass(frozen=True, slots=True)
class Answer:
    """A completed turn: what to say, what it rests on, and where to go next."""

    text: str
    route: Route
    resolution: Resolution
    citations: tuple[str, ...]
    source: str
    """``deterministic`` or the model name. Says which path produced the text."""

    degraded: bool = False
    """The model was meant to answer and could not. Worth surfacing, so an
    outage looks like an outage rather than a change of tone."""

    notes: tuple[str, ...] = field(default=())
    next_state: ConversationState = field(default_factory=ConversationState)

    @property
    def status(self) -> Status | None:
        return self.resolution.status

    @property
    def needs_a_human(self) -> bool:
        return self.route.needs_a_human

    @property
    def awaiting_answer(self) -> bool:
        """Whether the assistant has asked the user something and is waiting."""
        return self.resolution.outcome is Outcome.AMBIGUOUS

    def explain(self) -> str:
        return (
            f"{self.route.explain()} | {self.resolution.explain()} | "
            f"answered by {self.source}"
        )


class Pipeline:
    """Holds the loaded corpus and index, and runs turns against them."""

    def __init__(
        self,
        catalog: ServiceCatalog,
        index: KnowledgeIndex,
        *,
        model: LanguageModel | None = None,
        system_prompt: str | None = None,
        branches: tuple[str, ...] = (),
    ) -> None:
        self.catalog = catalog
        self.index = index
        self.retriever = InMemoryRetriever(index)
        self.resolver = ScopeResolver(catalog, self.retriever)
        self.router = Router(branches)
        self.model = model
        self._system_prompt = system_prompt

    @classmethod
    def load(cls, settings: Settings | None = None, **overrides: object) -> Pipeline:
        """Build a pipeline from configuration.

        Loading is total: a missing index yields keyword-free retrieval rather
        than a crash, and an unconfigured model yields deterministic answers.
        A missing *corpus* is fatal, because without it there are no verdicts
        and the assistant has nothing truthful to say.
        """
        settings = settings or get_settings()
        catalog = load_catalog(Manifest.load(settings.documents_dir)).catalog
        index = KnowledgeIndex.load_local(settings.local_index_path)

        if index.is_empty:
            logger.warning(
                "pipeline.no_index",
                detail="retrieval disabled; verdicts still resolve by name and alias",
            )

        return cls(
            catalog,
            index,
            model=build_model(settings),
            system_prompt=load_system_prompt(settings.system_prompt_path),
            **overrides,  # type: ignore[arg-type]
        )

    def prepare(
        self, question: str, state: ConversationState | None = None
    ) -> tuple[Route, Resolution, RetrievalResult, ContextPack]:
        """Everything up to the model call. Deterministic, and cheap to inspect."""
        state = state or ConversationState()
        route = self.router.route(question, state)

        if route.intent is Intent.HANDOVER:
            # Nothing is looked up. The point of a handover is that the
            # assistant does not engage with the substance at all, and
            # retrieving supporting documents would invite it to.
            resolution = Resolution(Outcome.UNKNOWN, question)
            retrieval = RetrievalResult(mode="skipped")
        else:
            resolution = self._resolve(question, route)
            retrieval = self.retriever.retrieve(
                question, limit=EVIDENCE_LIMIT, force_item_ids=resolution.force_item_ids
            )

        pack = build_context(
            route, resolution, retrieval, system_prompt=self._system_prompt
        )
        return route, resolution, retrieval, pack

    def answer(self, question: str, state: ConversationState | None = None) -> Answer:
        route, resolution, retrieval, pack = self.prepare(question, state)

        fallback = compose(route, resolution, retrieval)
        text, source, degraded = self._generate(pack, fallback, route)

        answer = Answer(
            text=text,
            route=route,
            resolution=resolution,
            citations=pack.citations,
            source=source,
            degraded=degraded,
            notes=pack.notes,
            next_state=_carry_forward(route, resolution),
        )
        logger.info("pipeline.answered", question=question, detail=answer.explain())
        return answer

    def _generate(
        self, pack: ContextPack, fallback: str, route: Route
    ) -> tuple[str, str, bool]:
        """Ask the model, and fall back without ceremony if it cannot answer."""
        if self.model is None:
            return fallback, DETERMINISTIC, False

        if route.intent is Intent.HANDOVER:
            # The handover wording is fixed and has been reviewed. Sending it
            # through a model could only rephrase a statement that says what
            # it needs to say already.
            return fallback, DETERMINISTIC, False

        reply = self.model.generate(pack.as_prompt())

        # Checked here rather than trusting the client, because every model
        # implementation has to clear this bar. Blank output is a real outcome
        # - safety filters and token exhaustion both produce it - and showing
        # it would look like the assistant had nothing to say.
        if reply.degraded or not reply.text.strip():
            logger.warning("pipeline.model_degraded", error=reply.error)
            return fallback, DETERMINISTIC, True
        return reply.text.strip(), reply.model, False

    def _resolve(self, question: str, route: Route) -> Resolution:
        """Work out which service the turn is about.

        Inherited context is a *fallback*, never a prefix. "And what about
        merch?" and "and for Bedford?" are both follow-ups, and only the second
        one lacks a subject of its own. Prepending the previous service to both
        meant the first was answered about the previous service - the user
        asked about merch and was told about translation, which is precisely
        the kind of confident wrong answer this system exists to avoid.

        No word count separates those two messages; only trying to resolve them
        does. So the message is resolved on its own terms first, and the
        previous subject is consulted only when that finds nothing.
        """
        if route.selected_item_id and (item := self.catalog.get(route.selected_item_id)):
            return self.resolver.resolve(item.display_name)

        resolution = self.resolver.resolve(question)
        if resolution.outcome is not Outcome.UNKNOWN or not route.carried_item_ids:
            return resolution

        previous = self.catalog.get(route.carried_item_ids[0])
        if previous is None:
            return resolution

        carried = self.resolver.resolve(f"{previous.display_name} {question}")
        return carried if carried.outcome is not Outcome.UNKNOWN else resolution


def _carry_forward(route: Route, resolution: Resolution) -> ConversationState:
    """What the next turn needs to know about this one."""
    return ConversationState(
        pending_candidates=(
            resolution.force_item_ids if resolution.outcome is Outcome.AMBIGUOUS else ()
        ),
        last_item_ids=resolution.force_item_ids,
        last_branch=route.branch,
        last_intent=route.intent,
    )
