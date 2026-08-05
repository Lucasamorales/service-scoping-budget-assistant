"""Assert what retrieval returns, without generating anything.

    python -m scripts.eval_retrieval
    python -m scripts.eval_retrieval --verbose
    python -m scripts.eval_retrieval --case leaflet-new-class

Fast, deterministic, and no model call. Run this before touching a prompt:
most bad answers are bad retrieval, and a prompt cannot rescue a pack that
never contained the right document.

A case passes at rank 1 when the expected item comes back first. Ranking
inside the top few still counts, because the resolver disambiguates by asking
rather than by silently taking the top hit - but rank 1 is what makes the
common path fast.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.errors import CatalogError
from app.core.types import Status
from app.knowledge.catalog import ServiceCatalog, load_catalog
from app.knowledge.index import KnowledgeIndex
from app.knowledge.manifest import Manifest
from app.knowledge.retriever import InMemoryRetriever

DEFAULT_CASES = Path("evals/retrieval.json")
DEFAULT_INDEX = Path("artifacts/index.json")
DEFAULT_DOCUMENTS_DIR = Path("documents")
TOP_K = 5


@dataclass(frozen=True, slots=True)
class Outcome:
    case_id: str
    prompt: str
    expected: str
    rank: int | None
    """1-based rank of the expected item, or None if absent from the top K."""

    accepted_alternate: str | None
    returned: tuple[str, ...]
    status_ok: bool
    note: str | None
    ambiguous: bool = False
    """The question points at items with different verdicts. Ranking must not
    settle it, so the bar is presence among the candidates, not first place."""

    explanation: tuple[tuple[str, float, tuple[str, ...]], ...] = ()
    """Per hit: item id, score and the terms that matched. Retrieval you cannot
    explain at runtime is retrieval you cannot debug."""

    @property
    def exact(self) -> bool:
        return self.rank == 1

    @property
    def found(self) -> bool:
        return self.rank is not None

    @property
    def passed(self) -> bool:
        if self.ambiguous:
            return self.found
        return self.exact or self.accepted_alternate is not None


def _evaluate(
    case: dict[str, Any],
    retriever: InMemoryRetriever,
    catalog: ServiceCatalog,
) -> Outcome:
    prompt = str(case["prompt"])
    expected = str(case["expect"])
    acceptable = {str(value) for value in case.get("acceptable", ())}

    result = retriever.retrieve(prompt, limit=TOP_K)
    returned = result.item_ids

    rank = returned.index(expected) + 1 if expected in returned else None
    alternate = None
    if rank != 1 and returned and returned[0] in acceptable:
        alternate = returned[0]

    status_ok = True
    if expected_status := case.get("expectStatus"):
        item = catalog.get(expected)
        status_ok = item is not None and item.status is Status(str(expected_status))

    return Outcome(
        case_id=str(case["id"]),
        prompt=prompt,
        expected=expected,
        rank=rank,
        accepted_alternate=alternate,
        returned=returned,
        status_ok=status_ok,
        note=str(case["note"]) if "note" in case else None,
        ambiguous=bool(case.get("requiresDisambiguation", False)),
        explanation=tuple(
            (hit.chunk.item_id or hit.chunk.source, hit.score, hit.matched) for hit in result.hits
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS_DIR)
    parser.add_argument("--case", help="Run a single case by id.")
    parser.add_argument("--verbose", action="store_true", help="Show every case, not just misses.")
    args = parser.parse_args()

    index = KnowledgeIndex.load_local(args.index)
    if index.is_empty:
        print(f"No index at {args.index}. Run `python -m scripts.build_index` first.")
        return 1

    try:
        catalog = load_catalog(Manifest.load(args.documents)).catalog
    except CatalogError as exc:
        print(f"Could not load the catalog: {exc}")
        return 1

    payload = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = payload["cases"]
    if args.case:
        cases = [case for case in cases if case["id"] == args.case]
        if not cases:
            print(f"No case with id {args.case!r}")
            return 1

    retriever = InMemoryRetriever(index)
    print(f"{len(index)} chunks indexed, retrieval mode keyword-only, top {TOP_K}.\n")

    outcomes = [_evaluate(case, retriever, catalog) for case in cases]

    for outcome in outcomes:
        if outcome.exact and not outcome.ambiguous and not args.verbose:
            continue
        marker = "PASS" if outcome.passed else "FAIL"
        where = f"rank {outcome.rank}" if outcome.found else f"not in top {TOP_K}"
        if outcome.ambiguous:
            where += ", ambiguous by design"
        print(f"[{marker}] {outcome.case_id}: {where}")
        print(f'       "{outcome.prompt}"')
        if not outcome.exact:
            print(f"       expected: {outcome.expected}")
            if outcome.accepted_alternate:
                print(f"       accepted alternate at rank 1: {outcome.accepted_alternate}")
            for position, (item_id, score, matched) in enumerate(
                outcome.explanation[:4], start=1
            ):
                marker = "<-" if item_id == outcome.expected else "  "
                print(f"    {marker} {position}. {score:5.2f}  {item_id}")
                print(f"           matched: {', '.join(matched) or 'nothing'}")
        if outcome.note:
            print(f"       note: {outcome.note}")
        print()

    total = len(outcomes)
    decisive = [outcome for outcome in outcomes if not outcome.ambiguous]
    ambiguous = [outcome for outcome in outcomes if outcome.ambiguous]
    passed = sum(outcome.passed for outcome in outcomes)
    found = sum(outcome.found for outcome in outcomes)
    bad_status = [outcome for outcome in outcomes if not outcome.status_ok]

    print("-" * 70)
    if decisive:
        exact = sum(outcome.exact for outcome in decisive)
        alternates = sum(
            outcome.accepted_alternate is not None and not outcome.exact for outcome in decisive
        )
        print(f"decisive cases:  {len(decisive)}")
        print(f"  rank 1:        {exact}/{len(decisive)} ({exact / len(decisive):.0%})")
        print(f"  equal-verdict alternate at rank 1: {alternates}")
    if ambiguous:
        held = sum(outcome.found for outcome in ambiguous)
        print(f"ambiguous cases: {len(ambiguous)}  candidate retained: {held}/{len(ambiguous)}")
    print(f"overall passed:  {passed}/{total} ({passed / total:.0%})")
    print(f"in top {TOP_K}:       {found}/{total} ({found / total:.0%})")

    if bad_status:
        print(
            f"\nVerdict mismatches ({len(bad_status)}) - "
            f"the eval file disagrees with the corpus:"
        )
        for outcome in bad_status:
            print(f"  {outcome.case_id}: {outcome.expected}")
        return 1

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
