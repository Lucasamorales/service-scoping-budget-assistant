"""Score the intent router against evals/routing.json.

    python -m scripts.eval_router
    python -m scripts.eval_router --verbose

No index, no catalog, no model call. Routing is pure pattern matching, so this
runs in milliseconds and is worth running on every change.

Two classes of failure, and they are not comparable:

- A **missed handover** means the assistant answered something it had no
  standing to answer: an injury, a legal threat, a data protection request.
  Any of these fails the run outright.
- A **misroute** between ordinary intents produces a poor answer, which is bad
  but recoverable in the next turn.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.orchestrator.router import ConversationState, Intent, Route, Router

DEFAULT_CASES = Path("evals/routing.json")


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    message: str
    expected: Intent
    critical: bool
    expected_topic: str | None
    expected_selection: str | None
    route: Route

    @property
    def intent_correct(self) -> bool:
        return self.route.intent is self.expected

    @property
    def topic_correct(self) -> bool:
        if self.expected_topic is None:
            return True
        topic = self.route.handover_topic
        return topic is not None and topic.name == self.expected_topic

    @property
    def selection_correct(self) -> bool:
        if self.expected_selection is None:
            return True
        return self.route.selected_item_id == self.expected_selection

    @property
    def passed(self) -> bool:
        return self.intent_correct and self.topic_correct and self.selection_correct

    @property
    def missed_a_handover(self) -> bool:
        """The assistant would have answered something it must not touch."""
        return self.critical and self.route.intent is not Intent.HANDOVER


def _state_from(raw: dict[str, Any] | None) -> ConversationState:
    if not raw:
        return ConversationState()
    return ConversationState(
        pending_candidates=tuple(raw.get("pendingCandidates", ())),
        last_item_ids=tuple(raw.get("lastItemIds", ())),
        last_branch=raw.get("lastBranch"),
    )


def _evaluate(case: dict[str, Any], router: Router) -> CaseResult:
    message = str(case["message"])
    return CaseResult(
        case_id=str(case["id"]),
        message=message,
        expected=Intent(str(case["expect"])),
        critical=bool(case.get("critical", False)),
        expected_topic=case.get("expectTopic"),
        expected_selection=case.get("expectSelected"),
        route=router.route(message, _state_from(case.get("state"))),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--case", help="Run a single case by id.")
    parser.add_argument("--verbose", action="store_true", help="Show every case.")
    args = parser.parse_args()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    if args.case:
        cases = [case for case in cases if case["id"] == args.case]
        if not cases:
            print(f"No case with id {args.case!r}")
            return 1

    router = Router()
    results = [_evaluate(case, router) for case in cases]

    for result in results:
        if result.passed and not args.verbose:
            continue
        print(f"[FAIL] {result.case_id}")
        print(f'       "{result.message}"')
        print(f"       expected {result.expected.value}, got {result.route.explain()}")
        if not result.topic_correct:
            actual = result.route.handover_topic
            got = actual.name if actual else "none"
            print(f"       expected topic {result.expected_topic}, got {got}")
        if not result.selection_correct:
            print(
                f"       expected selection {result.expected_selection}, "
                f"got {result.route.selected_item_id}"
            )
        print()

    total = len(results)
    passed = sum(result.passed for result in results)
    missed = [result for result in results if result.missed_a_handover]
    critical = [result for result in results if result.critical]
    by_intent = Counter(result.route.intent.value for result in results)

    print("-" * 70)
    print(f"  missed handovers:  {len(missed)}/{len(critical)} critical cases")
    print(f"  routed correctly:  {passed}/{total} ({passed / total:.0%})")
    print(f"\nrouted as: {', '.join(f'{k} {v}' for k, v in sorted(by_intent.items()))}")

    if missed:
        print("\nMissed handovers, each one an answer the assistant must not give:")
        for result in missed:
            print(f"  {result.case_id}: routed to {result.route.intent.value}")

    return 1 if missed or passed != total else 0


if __name__ == "__main__":
    raise SystemExit(main())
