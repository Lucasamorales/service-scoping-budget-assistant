"""Route a matrix of realistic utterances through the pipeline and report where they land.

    python -m scripts.probe_intents            # deterministic only (no model call)
    python -m scripts.probe_intents --model    # allow Gemini wording turns

Prints one line per utterance: intent, what matched, resolver outcome, and the
first line of the reply. Intended for spotting misroutes in bulk rather than
one question at a time.
"""

from __future__ import annotations

import argparse
import sys

from app.core.config import get_settings
from app.orchestrator.pipeline import Pipeline
from app.orchestrator.router import ConversationState
from app.tools.flows import SessionIdentity

# Grouped by what an Account Manager is actually trying to do.
PROBES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "inventory",
        (
            "give me a list of services",
            "what can you help me with",
            "what else can you do for me",
            "which things are free and which cost money",
            "show me everything under events",
            "what do I get for free",
        ),
    ),
    (
        "scoping",
        (
            "can we do merch for the london branch",
            "we need a billboard near the motorway",
            "is a photoshoot included",
            "our landlord wants signage at the entrance, who pays",
            "I want to run a valentines campaign with video",
            "do you handle translating our web pages",
        ),
    ),
    (
        "budget",
        (
            "what's left for london",
            "how much budget does manchester have",
            "and manchester?",
            "how are we doing on spend in the uk",
            "do we have money for a photoshoot in basingstoke",
        ),
    ),
    (
        "quote / price",
        (
            "how much would a billboard cost",
            "what's the price for merch",
            "can you quote a photoshoot",
        ),
    ),
    (
        "action / mail",
        (
            "email my AM about the merch request",
            "yes",
            "no thanks",
        ),
    ),
    (
        "handover / safety",
        (
            "a customer got injured during a photoshoot, can we post about it",
            "a journalist is asking about our new branch",
        ),
    ),
    (
        "off-piste",
        (
            "hi",
            "what's the weather like",
            "who is my account manager",
            "remind me what we agreed last week",
        ),
    ),
)


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="store_true", help="Allow Gemini wording turns.")
    parser.add_argument(
        "--sticky",
        action="store_true",
        help="Carry state between probes in a group, as a real conversation does.",
    )
    args = parser.parse_args()
    _force_utf8_output()

    pipeline = Pipeline.load(get_settings())
    if not args.model:
        pipeline.model = None

    identity = SessionIdentity(subject="probe", role="am")
    for group, questions in PROBES:
        print(f"\n=== {group} ===")
        state = ConversationState()
        for question in questions:
            answer = pipeline.answer(
                question, state if args.sticky else ConversationState(), identity=identity
            )
            first = answer.text.strip().splitlines()[0][:88]
            print(f"  {question!r}")
            print(f"    route    {answer.route.explain()}")
            print(f"    resolver {answer.resolution.explain()}")
            print(f"    reply    [{answer.source}] {first}")
            state = answer.next_state
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
