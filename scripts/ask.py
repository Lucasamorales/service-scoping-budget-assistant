"""Run a question through the whole pipeline and print what the model would see.

    python -m scripts.ask "can we do a billboard for the new branch"
    python -m scripts.ask "translate our web pages" --prompt
    python -m scripts.ask            # interactive

No model call, no API key, no network. Everything up to the moment of
generation is deterministic, so this shows the real route, the real verdict and
the real prompt.

This is the fastest way to answer "why did it say that?", and it works before
Vertex AI is wired up at all.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.core.errors import CatalogError
from app.knowledge.catalog import load_catalog
from app.knowledge.index import KnowledgeIndex
from app.knowledge.manifest import Manifest
from app.knowledge.retriever import InMemoryRetriever, RetrievalResult
from app.orchestrator.context import build_context
from app.orchestrator.resolver import Outcome, Resolution, ScopeResolver
from app.orchestrator.router import ConversationState, Intent, Route, Router

DEFAULT_INDEX = Path("artifacts/index.json")
DEFAULT_DOCUMENTS_DIR = Path("documents")
EVIDENCE_LIMIT = 4

RULE = "-" * 74


class Pipeline:
    """Everything that happens before the model is called."""

    def __init__(self, documents: Path, index_path: Path) -> None:
        self.catalog = load_catalog(Manifest.load(documents)).catalog
        self.index = KnowledgeIndex.load_local(index_path)
        self.retriever = InMemoryRetriever(self.index)
        self.resolver = ScopeResolver(self.catalog, self.retriever)
        self.router = Router()

    def run(
        self, question: str, state: ConversationState
    ) -> tuple[Route, Resolution, RetrievalResult]:
        route = self.router.route(question, state)

        if route.intent is Intent.HANDOVER:
            # Nothing is looked up. The point of a handover is that the
            # assistant does not engage with the substance at all.
            resolution = Resolution(Outcome.UNKNOWN, question)
            return route, resolution, RetrievalResult(mode="skipped")

        resolution = self.resolver.resolve(question)
        retrieval = self.retriever.retrieve(
            question, limit=EVIDENCE_LIMIT, force_item_ids=resolution.force_item_ids
        )
        return route, resolution, retrieval


def show(
    pipeline: Pipeline, question: str, state: ConversationState, full_prompt: bool
) -> tuple[Route, Resolution]:
    route, resolution, retrieval = pipeline.run(question, state)
    pack = build_context(route, resolution, retrieval)

    print(f"\n{RULE}\n  {question}\n{RULE}")
    print(f"\nROUTE      {route.explain()}")
    print(f"RESOLVER   {resolution.explain()}")
    print(f"RETRIEVAL  {retrieval.citation_line()}")

    if resolution.decided:
        print(f"\nVERDICT    {resolution.status_meaning}")
    elif question_text := resolution.question():
        print(f"\nMUST ASK\n{question_text}")

    print(f"\nCITED      {'; '.join(pack.citations)}")
    if pack.notes:
        for note in pack.notes:
            print(f"NOTE       {note}")
    print(f"TOKENS     ~{pack.estimated_tokens}")

    if full_prompt:
        print(f"\n{RULE}\nPROMPT SENT TO THE MODEL\n{RULE}")
        print(pack.as_prompt())

    return route, resolution


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="*", help="The question to ask.")
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS_DIR)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--prompt", action="store_true", help="Print the assembled prompt.")
    args = parser.parse_args()

    try:
        pipeline = Pipeline(args.documents, args.index)
    except CatalogError as exc:
        print(f"Could not load the corpus: {exc}")
        return 1

    if pipeline.index.is_empty:
        print(f"No index at {args.index}. Run `python -m scripts.build_index` first.")
        return 1

    if args.question:
        show(pipeline, " ".join(args.question), ConversationState(), args.prompt)
        return 0

    print("Ask a question, or press Enter on an empty line to quit.")
    state = ConversationState()
    while True:
        try:
            question = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if not question:
            return 0

        route, resolution = show(pipeline, question, state, args.prompt)

        # Carry the turn forward so follow-ups and clarifying replies behave
        # here exactly as they will in the real conversation.
        state = ConversationState(
            pending_candidates=(
                resolution.force_item_ids if resolution.outcome is Outcome.AMBIGUOUS else ()
            ),
            last_item_ids=resolution.force_item_ids,
            last_branch=route.branch,
            last_intent=route.intent,
        )


if __name__ == "__main__":
    raise SystemExit(main())
