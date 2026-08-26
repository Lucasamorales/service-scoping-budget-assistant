"""Score the scope resolver against the same cases retrieval is scored on.

    python -m scripts.eval_resolver
    python -m scripts.eval_resolver --verbose

Retrieval finding the right document is necessary but not sufficient. What
reaches the user is the *verdict*, so this measures that directly.

The bar differs by case, and deliberately so:

- A normal case must produce the right verdict. Naming the exact item is
  better, but where two items agree about scope the answer is already correct.
- A case marked ``requiresDisambiguation`` names items whose verdicts differ.
  Producing a confident verdict there is a **failure**, however plausible it
  looks, because ranking is not allowed to make that choice. The pass condition
  is that the resolver asks.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.errors import CatalogError
from app.core.types import Status
from app.knowledge.catalog import load_catalog
from app.knowledge.index import KnowledgeIndex
from app.knowledge.manifest import Manifest
from app.knowledge.retriever import InMemoryRetriever
from app.orchestrator.resolver import Outcome, Resolution, ScopeResolver

DEFAULT_CASES = Path("evals/retrieval.json")
DEFAULT_INDEX = Path("artifacts/index.json")
DEFAULT_DOCUMENTS_DIR = Path("documents")


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    prompt: str
    expected_item: str
    expected_status: Status | None
    ambiguous: bool
    resolution: Resolution
    known_failure: str | None = None
    """Why this case is expected to fail, and what will fix it.

    Shares the case file with ``eval_retrieval``, so a case marked once is
    recorded in both. A recorded baseline still runs and is still printed; it
    just does not gate the exit code, and it is reported if it starts passing
    so the marker gets removed rather than accumulating."""

    @property
    def named_the_item(self) -> bool:
        return self.resolution.item is not None and (
            self.resolution.item.item_id == self.expected_item
        )

    @property
    def verdict_correct(self) -> bool:
        return (
            self.expected_status is not None
            and self.resolution.status is self.expected_status
        )

    @property
    def stated_a_wrong_verdict(self) -> bool:
        """The only outcome that actually harms anyone.

        For a case whose candidates disagree about scope, stating *any* verdict
        is wrong, even the expected one: it means ranking decided something
        that only the user can decide, and it was right by luck.
        """
        if not self.resolution.decided:
            return False
        return self.ambiguous or not self.verdict_correct

    @property
    def answered_well(self) -> bool:
        """Gave the right verdict, or asked when asking was the right move."""
        if self.ambiguous:
            return self.resolution.outcome is Outcome.AMBIGUOUS
        return self.verdict_correct

    @property
    def passed(self) -> bool:
        return self.answered_well

    @property
    def marker(self) -> str:
        """How this case is labelled in the report."""
        if self.passed:
            return "PASS"
        return "known" if self.known_failure else "FAIL"

    @property
    def verdict_label(self) -> str:
        status = self.resolution.status
        return status.value if status else f"({self.resolution.outcome.value})"


def _evaluate(case: dict[str, Any], resolver: ScopeResolver) -> CaseResult:
    raw_status = case.get("expectStatus")
    return CaseResult(
        case_id=str(case["id"]),
        prompt=str(case["prompt"]),
        expected_item=str(case["expect"]),
        expected_status=Status(str(raw_status)) if raw_status else None,
        ambiguous=bool(case.get("requiresDisambiguation", False)),
        resolution=resolver.resolve(str(case["prompt"])),
        known_failure=str(case["knownFailure"]) if "knownFailure" in case else None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS_DIR)
    parser.add_argument("--case", help="Run a single case by id.")
    parser.add_argument("--verbose", action="store_true", help="Show every case.")
    args = parser.parse_args()

    try:
        catalog = load_catalog(Manifest.load(args.documents)).catalog
    except CatalogError as exc:
        print(f"Could not load the catalog: {exc}")
        return 1

    index = KnowledgeIndex.load_local(args.index)
    if index.is_empty:
        print(f"No index at {args.index}. Run `python -m scripts.build_index` first.")
        return 1

    resolver = ScopeResolver(catalog, InMemoryRetriever(index))

    cases = json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    if args.case:
        cases = [case for case in cases if case["id"] == args.case]
        if not cases:
            print(f"No case with id {args.case!r}")
            return 1

    results = [_evaluate(case, resolver) for case in cases]

    for result in results:
        if result.passed and result.named_the_item and not args.verbose:
            continue
        print(f"[{result.marker}] {result.case_id}: {result.verdict_label}")
        if result.known_failure:
            print(f"       known: {result.known_failure}")
        print(f'       "{result.prompt}"')
        print(f"       {result.resolution.explain()}")
        if result.ambiguous:
            print("       must ask: verdicts differ between the candidates")
        elif not result.named_the_item and result.verdict_correct:
            print(f"       verdict right, exact item not named (wanted {result.expected_item})")
        elif not result.verdict_correct:
            expected = result.expected_status.value if result.expected_status else "?"
            print(f"       expected {expected}, got {result.verdict_label}")
        print()

    total = len(results)
    dangerous = [result for result in results if result.stated_a_wrong_verdict]
    answered = sum(result.answered_well for result in results)
    named = sum(result.named_the_item for result in results)
    over_cautious = [
        result
        for result in results
        if not result.ambiguous and not result.resolution.decided
    ]
    outcomes = Counter(result.resolution.outcome.value for result in results)
    methods = Counter(result.resolution.method for result in results)

    print("-" * 70)
    print("Wrong verdicts are the only failures that reach a user as bad advice.")
    print("Asking or handing over costs a turn and is safe.\n")
    print(f"  stated a WRONG verdict:   {len(dangerous)}/{total}")
    print(f"  answered well:            {answered}/{total} ({answered / total:.0%})")
    print(f"  named the exact item:     {named}/{total}")
    print(f"  asked or handed over when it could have answered: {len(over_cautious)}/{total}")
    print(f"\noutcomes: {', '.join(f'{k} {v}' for k, v in sorted(outcomes.items()))}")
    print(f"resolved via: {', '.join(f'{k} {v}' for k, v in sorted(methods.items()))}")

    if dangerous:
        print("\nWrong verdicts:")
        for result in dangerous:
            expected = result.expected_status.value if result.expected_status else "an ask"
            marker = " [known]" if result.known_failure else ""
            print(f"  {result.case_id}: said {result.verdict_label}, expected {expected}{marker}")

    if fixed := [r for r in results if r.passed and r.known_failure]:
        print("\nMarked as known failures but now passing - remove the marker:")
        for result in fixed:
            print(f"  {result.case_id}")

    # Only an *unrecorded* wrong verdict fails the run. Over-caution is
    # reported, not gated: it is a cost, and tuning it away against 25
    # handwritten cases would overfit to them.
    return 1 if [r for r in dangerous if not r.known_failure] else 0


if __name__ == "__main__":
    raise SystemExit(main())
