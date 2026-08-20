"""Score whole turns against evals/turns.json.

    python -m scripts.eval_turns                # rules only, no model calls
    python -m scripts.eval_turns --planner      # let the model plan the turns
    python -m scripts.eval_turns --model        # planner and wording both live
    python -m scripts.eval_turns --case list-free-things --verbose

Unlike ``scripts.eval_router`` this runs the real pipeline: catalog, index,
budget Sheet, quote card. It asks the two questions a user would ask.

- **Did the turn reach the right capability?** A budget question answered from
  the service catalog reads like a normal reply and is simply wrong.
- **Did the reply carry the right facts?** ``mustInclude`` / ``mustNotInclude``
  catch the failures that routing alone cannot see, such as a free-of-charge
  promise for something the local team owns.

Cases marked ``critical`` mislead someone about safety or about money. Any
critical failure fails the run regardless of the overall rate.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.errors import CatalogError
from app.orchestrator.pipeline import Answer, Pipeline
from app.orchestrator.plan import Capability, Plan
from app.orchestrator.router import ConversationState
from app.tools.flows import SessionIdentity

DEFAULT_CASES = Path("evals/turns.json")
RULE = "-" * 74


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    message: str
    expected: tuple[Capability, ...]
    forbidden: tuple[Capability, ...]
    must_include: tuple[str, ...]
    must_not_include: tuple[str, ...]
    critical: bool
    answer: Answer

    @property
    def plan(self) -> Plan | None:
        return self.answer.plan

    @property
    def planned(self) -> tuple[Capability, ...]:
        return self.plan.capabilities if self.plan else ()

    @property
    def ran(self) -> tuple[Capability, ...]:
        """What the turn actually did, which is what the user experiences.

        Asserting on this rather than on the plan is deliberate: a lookup that
        was planned and found nothing has not answered anything, and a plan
        that named the wrong capability is only a failure if the answer went
        out that way.
        """
        return self.answer.satisfied or self.planned

    @property
    def missing(self) -> tuple[Capability, ...]:
        return tuple(c for c in self.expected if c not in self.ran)

    @property
    def forbidden_hits(self) -> tuple[Capability, ...]:
        return tuple(c for c in self.forbidden if c in self.ran)

    @property
    def absent_text(self) -> tuple[str, ...]:
        body = self.answer.text.lower()
        return tuple(term for term in self.must_include if term.lower() not in body)

    @property
    def present_text(self) -> tuple[str, ...]:
        body = self.answer.text.lower()
        return tuple(term for term in self.must_not_include if term.lower() in body)

    @property
    def routed(self) -> bool:
        return not self.missing and not self.forbidden_hits

    @property
    def worded(self) -> bool:
        return not self.absent_text and not self.present_text

    @property
    def passed(self) -> bool:
        return self.routed and self.worded


def _state_from(raw: dict[str, Any] | None) -> ConversationState:
    if not raw:
        return ConversationState()
    return ConversationState(
        pending_candidates=tuple(raw.get("pendingCandidates", ())),
        last_item_ids=tuple(raw.get("lastItemIds", ())),
        last_branch=raw.get("lastBranch"),
        pending_action_kind=raw.get("pendingActionKind"),
        pending_service_id=raw.get("pendingServiceId"),
        pending_quote_amount=raw.get("pendingQuoteAmount"),
        pending_recipient_country=raw.get("pendingRecipientCountry"),
        pending_needs_country=bool(raw.get("pendingNeedsCountry", False)),
        active_tool=raw.get("activeTool"),
        budget_country=raw.get("budgetCountry"),
        budget_branch=raw.get("budgetBranch"),
        budget_month=raw.get("budgetMonth"),
    )


def _capabilities(raw: Any) -> tuple[Capability, ...]:
    if not raw:
        return ()
    return tuple(Capability(str(entry)) for entry in raw)


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _run(case: dict[str, Any], pipeline: Pipeline) -> CaseResult:
    message = str(case["message"])
    answer = pipeline.answer(
        message,
        _state_from(case.get("state")),
        identity=SessionIdentity(subject="eval", role="am"),
    )
    return CaseResult(
        case_id=str(case["id"]),
        message=message,
        expected=_capabilities(case.get("expect")),
        forbidden=_capabilities(case.get("forbid")),
        must_include=tuple(case.get("mustInclude", ())),
        must_not_include=tuple(case.get("mustNotInclude", ())),
        critical=bool(case.get("critical", False)),
        answer=answer,
    )


def _report(result: CaseResult) -> None:
    print(f"[FAIL{' CRITICAL' if result.critical else ''}] {result.case_id}")
    print(f'         "{result.message}"')
    ran = ", ".join(c.value for c in result.ran) or "none"
    if result.missing:
        print(f"         expected {', '.join(c.value for c in result.missing)}; ran {ran}")
        print(f"         planned {', '.join(c.value for c in result.planned) or 'none'}")
    if result.forbidden_hits:
        print(f"         must not plan {', '.join(c.value for c in result.forbidden_hits)}")
    if result.absent_text:
        print(f"         reply is missing {result.absent_text}")
    if result.present_text:
        print(f"         reply should not contain {result.present_text}")
    first = result.answer.text.strip().splitlines()[0][:96] if result.answer.text else ""
    print(f"         got [{result.answer.source}] {first}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--case", help="Run a single case by id.")
    parser.add_argument("--verbose", action="store_true", help="Show every case.")
    parser.add_argument("--planner", action="store_true", help="Let the model plan.")
    parser.add_argument(
        "--model",
        action="store_true",
        help="Let the model plan and word the answers (slower, non-deterministic).",
    )
    args = parser.parse_args()
    _force_utf8_output()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    if args.case:
        cases = [case for case in cases if case["id"] == args.case]
        if not cases:
            print(f"No case with id {args.case!r}")
            return 1

    settings = get_settings().model_copy(
        update={"use_llm_planner": args.planner or args.model}
    )
    try:
        pipeline = Pipeline.load(settings)
    except (CatalogError, OSError) as exc:
        print(f"Could not start: {exc}")
        return 1
    if not args.model:
        # Wording off by default so a failure is attributable to routing.
        pipeline.model = None

    results = [_run(case, pipeline) for case in cases]

    for result in results:
        if result.passed and not args.verbose:
            continue
        if result.passed:
            print(f"[ok]     {result.case_id}: {', '.join(c.value for c in result.ran)}")
            continue
        _report(result)

    total = len(results)
    passed = [r for r in results if r.passed]
    misrouted = [r for r in results if not r.routed]
    misworded = [r for r in results if r.routed and not r.worded]
    critical = [r for r in results if r.critical]
    failed_critical = [r for r in critical if not r.passed]
    planned = Counter(c.value for r in results for c in r.ran)

    print(RULE)
    print(f"  turns correct:        {len(passed)}/{total} ({len(passed) / total:.0%})")
    print(f"  misrouted:            {len(misrouted)}")
    print(f"  routed but misworded: {len(misworded)}")
    print(f"  critical failures:    {len(failed_critical)}/{len(critical)}")
    print(f"\nplanned: {', '.join(f'{k} {v}' for k, v in sorted(planned.items()))}")

    if failed_critical:
        print("\nCritical failures — each one misleads someone about safety or money:")
        for result in failed_critical:
            print(f"  {result.case_id}")

    return 1 if failed_critical or len(passed) != total else 0


if __name__ == "__main__":
    raise SystemExit(main())
