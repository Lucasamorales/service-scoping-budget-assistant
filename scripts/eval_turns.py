"""Score whole turns against evals/turns.json.

    python -m scripts.eval_turns                     # rules only, no model calls
    python -m scripts.eval_turns --mode deployed     # what production runs
    python -m scripts.eval_turns --case list-free-things --verbose

Unlike ``scripts.eval_router`` this runs the real pipeline: catalog, index,
budget Sheet, quote card. It asks the three questions a user would ask.

- **Did the turn reach the right capability?** A budget question answered from
  the service catalog reads like a normal reply and is simply wrong.
- **Did it identify the right service?** ``expectItem`` / ``expectVerdict`` /
  ``expectOutcome`` assert what was actually decided. Without them a case
  passes whenever the right *tool* ran, which is how a request for Instagram
  scheduling could be answered from Marketing calendars and still score green.
- **Did the reply carry the right facts?** ``mustInclude`` / ``mustNotInclude``
  catch what the other two cannot see, such as a free-of-charge promise for
  something the local team owns.

The second group is the one that earns its keep. Capability assertions test
that the plumbing routes; only the verdict assertions test the product.

Cases marked ``critical`` mislead someone about safety or about money. Any
critical failure fails the run regardless of the overall rate.

A case may carry ``knownFailure``: a defect that is recorded, understood and
scheduled, naming the task that will fix it. Those still run and still print,
they simply do not gate the exit code — so the suite can gate CI from day one
instead of being red for a fortnight, which is how a signal stops being read.
Removing a marker is part of the fix, and the run says so when one is stale.

Modes exist because the deployed configuration and the deterministic one fail
differently, and only one of them is cheap enough to run on every push:

``rules``
    No network at all: no planner, no composer, and no embedder, so retrieval
    scores on words alone. Fast, free, repeatable, and the mode CI gates on. A
    failure here is attributable to routing or lookup, never to phrasing.

``planner``
    The model chooses capabilities and fills slots, and the resolver may embed
    the phrase it is resolving; wording stays deterministic. Isolates planning
    and retrieval defects from wording ones.

``deployed``
    Everything live. This is what production runs, so it is the only mode that
    can reproduce a defect in the seam between the model and the tools. Costs
    money and is not repeatable — run it nightly, not per-commit.

The embedder is tied to the mode rather than to whether a key happens to be
present. Otherwise the same command means different things on a laptop and in
CI, which is the exact drift the verdict assertions above were added to close.
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
from app.core.types import Status
from app.orchestrator.pipeline import Answer, Pipeline
from app.orchestrator.plan import Capability, Plan
from app.orchestrator.resolver import Outcome
from app.orchestrator.router import ConversationState
from app.tools.flows import SessionIdentity

DEFAULT_CASES = Path("evals/turns.json")
RULE = "-" * 74

MODES = ("rules", "planner", "deployed")
"""Run configurations, cheapest first. See the module docstring."""


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    message: str
    expected: tuple[Capability, ...]
    forbidden: tuple[Capability, ...]
    must_include: tuple[str, ...]
    must_not_include: tuple[str, ...]
    expect_item: str | None
    expect_verdict: Status | None
    expect_outcome: Outcome | None
    known_failure: str | None
    """Why this case is expected to fail, and which task will fix it.

    A recorded baseline, not a silenced one. The case still runs, still prints,
    and still shows in the counts; it just does not gate the exit code, so CI
    can be green and meaningful on day one instead of permanently red — a red
    nobody is required to act on is the same as no signal at all. Marked cases
    that start passing are reported so the marker gets removed."""

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
    def named_items(self) -> tuple[str, ...]:
        """Every item the resolver put forward, in its own order."""
        return tuple(c.item.item_id for c in self.answer.resolution.candidates)

    @property
    def wrong_item(self) -> str | None:
        """What the turn settled on, when that is not what the case expects.

        An expected item has to appear among the candidates *and* the resolver
        has to have reached a verdict. Naming the right service inside a
        question it never answered is not the same as answering it, and the
        two used to be indistinguishable here.
        """
        if self.expect_item is None:
            return None
        resolution = self.answer.resolution
        if not resolution.decided:
            return f"no verdict reached ({resolution.outcome.value})"
        if self.expect_item not in self.named_items:
            return ", ".join(self.named_items) or "nothing"
        return None

    @property
    def wrong_verdict(self) -> str | None:
        """The verdict the user was given, when it is not the expected one.

        This is the assertion that costs money when it is missing: every
        confidently-wrong answer this product can produce shows up here first.
        """
        if self.expect_verdict is None:
            return None
        actual = self.answer.resolution.status
        if actual is self.expect_verdict:
            return None
        return actual.value if actual else "none"

    @property
    def wrong_outcome(self) -> str | None:
        """Whether the turn asked, answered or gave up when it should not have.

        Needed because "ask the user" and "say you do not know" are both
        correct answers to some requests, and neither can be expressed as an
        expected item or verdict.
        """
        if self.expect_outcome is None:
            return None
        actual = self.answer.resolution.outcome
        return None if actual is self.expect_outcome else actual.value

    @property
    def routed(self) -> bool:
        return not self.missing and not self.forbidden_hits

    @property
    def identified(self) -> bool:
        """Whether the turn decided on the right service and verdict."""
        return not (self.wrong_item or self.wrong_verdict or self.wrong_outcome)

    @property
    def worded(self) -> bool:
        return not self.absent_text and not self.present_text

    @property
    def passed(self) -> bool:
        return self.routed and self.identified and self.worded

    @property
    def marker(self) -> str:
        """How this case is labelled in the report."""
        if self.passed:
            return "ok"
        return "known" if self.known_failure else "FAIL"


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


def _verdict(raw: Any) -> Status | None:
    """Parse an expected verdict, refusing anything the corpus does not use.

    Raising rather than defaulting is the point: a typo in ``expectVerdict``
    that silently disabled the assertion would restore exactly the blind spot
    these fields were added to close.
    """
    if raw is None:
        return None
    try:
        return Status(str(raw))
    except ValueError:
        valid = ", ".join(s.value for s in Status)
        raise ValueError(f"Unknown expectVerdict {raw!r}. Use one of: {valid}") from None


def _outcome(raw: Any) -> Outcome | None:
    if raw is None:
        return None
    try:
        return Outcome(str(raw))
    except ValueError:
        valid = ", ".join(o.value for o in Outcome)
        raise ValueError(f"Unknown expectOutcome {raw!r}. Use one of: {valid}") from None


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
        expect_item=case.get("expectItem"),
        expect_verdict=_verdict(case.get("expectVerdict")),
        expect_outcome=_outcome(case.get("expectOutcome")),
        known_failure=case.get("knownFailure"),
        critical=bool(case.get("critical", False)),
        answer=answer,
    )


def _report(result: CaseResult) -> None:
    print(f"[{result.marker}{' CRITICAL' if result.critical else ''}] {result.case_id}")
    if result.known_failure:
        print(f"         known: {result.known_failure}")
    print(f'         "{result.message}"')
    ran = ", ".join(c.value for c in result.ran) or "none"
    if result.missing:
        print(f"         expected {', '.join(c.value for c in result.missing)}; ran {ran}")
        print(f"         planned {', '.join(c.value for c in result.planned) or 'none'}")
    if result.forbidden_hits:
        print(f"         must not plan {', '.join(c.value for c in result.forbidden_hits)}")
    if wrong := result.wrong_item:
        print(f"         expected item {result.expect_item}; named {wrong}")
    if wrong := result.wrong_verdict:
        print(f"         expected verdict {result.expect_verdict}; said {wrong}")
    if wrong := result.wrong_outcome:
        print(f"         expected to {result.expect_outcome}; it {wrong}")
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
    parser.add_argument(
        "--mode",
        choices=MODES,
        default="rules",
        help="Run configuration (default: rules). See the module docstring.",
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
        update={
            "use_llm_planner": args.mode in ("planner", "deployed"),
            "use_dense_retrieval": args.mode != "rules",
        }
    )
    try:
        pipeline = Pipeline.load(settings)
    except (CatalogError, OSError) as exc:
        print(f"Could not start: {exc}")
        return 1
    if args.mode != "deployed":
        # Wording off unless we are reproducing production, so a failure is
        # attributable to routing and lookup rather than to phrasing.
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
    misidentified = [r for r in results if r.routed and not r.identified]
    misworded = [r for r in results if r.routed and r.identified and not r.worded]
    critical = [r for r in results if r.critical]
    failed_critical = [r for r in critical if not r.passed and not r.known_failure]
    known = [r for r in results if not r.passed and r.known_failure]
    planned = Counter(c.value for r in results for c in r.ran)

    # Counted and printed because it is the number that made the previous
    # harness look healthier than the product was: a case with no verdict
    # assertion passes as soon as the right tool runs.
    unasserted = [
        r for r in results if not (r.expect_item or r.expect_verdict or r.expect_outcome)
    ]

    print(RULE)
    print(f"  mode:                 {args.mode}")
    print(f"  turns correct:        {len(passed)}/{total} ({len(passed) / total:.0%})")
    print(f"  misrouted:            {len(misrouted)}")
    print(f"  wrong item/verdict:   {len(misidentified)}")
    print(f"  routed but misworded: {len(misworded)}")
    print(f"  critical failures:    {len(failed_critical)}/{len(critical)}")
    print(f"  known failures:       {len(known)} (recorded baseline, not gating)")
    print(f"  no verdict asserted:  {len(unasserted)}/{total}")
    print(f"\nplanned: {', '.join(f'{k} {v}' for k, v in sorted(planned.items()))}")

    if failed_critical:
        print("\nCritical failures — each one misleads someone about safety or money:")
        for result in failed_critical:
            print(f"  {result.case_id}")

    if fixed := [r for r in results if r.passed and r.known_failure]:
        print("\nMarked as known failures but now passing — remove the marker:")
        for result in fixed:
            print(f"  {result.case_id}")

    # Only an *unrecorded* failure gates. Recorded ones stay visible in the
    # counts above and in each case's report, so the debt is impossible to
    # miss without making the signal one people learn to ignore.
    unexpected = [r for r in results if not r.passed and not r.known_failure]
    return 1 if unexpected else 0


if __name__ == "__main__":
    raise SystemExit(main())
