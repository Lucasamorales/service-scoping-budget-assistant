"""Ask the assistant a question from the terminal.

    python -m scripts.ask "can we do a billboard for the new branch"
    python -m scripts.ask "translate our web pages" --trace
    python -m scripts.ask --prompt "merch"      # show what the model is sent
    python -m scripts.ask                       # interactive, carries context

Runs the same pipeline the deployed service runs. With no ``GEMINI_API_KEY``
it answers deterministically from the catalog, which needs no network, so the
whole thing is usable today.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import CatalogError
from app.orchestrator.pipeline import Answer, Pipeline
from app.orchestrator.router import ConversationState

RULE = "-" * 74


def _force_utf8_output() -> None:
    """Print the corpus's own punctuation intact on a Windows console.

    The default there is cp1252, which cannot encode the em dashes and curly
    quotes the documents contain. Fixing the stream rather than stripping the
    characters keeps what is printed identical to what the model is sent.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def print_answer(answer: Answer, *, trace: bool) -> None:
    print(f"\n{RULE}")
    print(answer.text)

    if answer.degraded:
        print("\n[the model was unreachable, so this is the deterministic answer]")

    for note in answer.notes:
        print(f"\n[{note}]")

    if trace:
        print(f"\n{RULE}")
        if answer.plan is not None:
            print(f"PLAN       {answer.plan.explain()}")
        if answer.satisfied:
            print(f"RAN        {', '.join(c.value for c in answer.satisfied)}")
        print(f"ROUTE      {answer.route.explain()}")
        print(f"RESOLVER   {answer.resolution.explain()}")
        print(f"ANSWERED   {answer.source}")
        print(f"CITED      {'; '.join(answer.citations)}")
        if answer.awaiting_answer:
            print("WAITING    on the user to choose")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="*", help="The question to ask.")
    parser.add_argument("--trace", action="store_true", help="Show how the answer was reached.")
    parser.add_argument("--prompt", action="store_true", help="Print the assembled prompt.")
    parser.add_argument("--documents", type=Path, help="Override the documents directory.")
    parser.add_argument("--index", type=Path, help="Override the index artifact.")
    args = parser.parse_args()
    _force_utf8_output()

    settings = get_settings()
    if args.documents:
        settings = settings.model_copy(update={"documents_dir": args.documents})
    if args.index:
        settings = settings.model_copy(update={"local_index_path": args.index})

    try:
        pipeline = Pipeline.load(settings)
    except (CatalogError, OSError) as exc:
        print(f"Could not start: {exc}")
        return 1

    if pipeline.model is None:
        print("[no GEMINI_API_KEY configured; answering from the catalog without a model]")

    def handle(question: str, state: ConversationState) -> ConversationState:
        if args.prompt:
            turn = pipeline.prepare(question, state)
            briefing = turn.briefing()
            print(f"\n{RULE}\nBRIEFING SENT TO THE MODEL\n{RULE}")
            print(briefing)
            print(f"{RULE}\n~{len(briefing.split())} words")

        answer = pipeline.answer(question, state)
        print_answer(answer, trace=args.trace or args.prompt)
        return answer.next_state

    if args.question:
        handle(" ".join(args.question), ConversationState())
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
        state = handle(question, state)


if __name__ == "__main__":
    raise SystemExit(main())
