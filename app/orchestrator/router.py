"""Deciding what kind of request this is, before deciding what to look up.

Retrieval is a workflow decision before it is a similarity problem. "How much
budget is left at Basingstoke?" and "can you do us a billboard?" need different
sources, different tools and different answers, and no amount of semantic
search turns one into the other. So the intent is settled first, by pattern,
and the rest of the pipeline is chosen from it.

Patterns rather than a model call, for the same reason the verdict is a lookup:
this decision gates what the assistant is allowed to do, so user text must not
be able to argue with it. It is also free and instant, which matters when the
first thing every turn does is run it.

Order is the load-bearing part. Handover is checked before anything else, so a
message about an injury is never treated as a scoping question just because it
also mentions photography.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from enum import StrEnum

import structlog

from app.core.keys import content_tokens, normalize_term, branch_key
from app.tools.catalog import wants_service_list
from app.tools.flows import is_affirmative

__all__ = [
    "ConversationState",
    "HandoverTopic",
    "Intent",
    "Route",
    "Router",
]

logger = structlog.get_logger(__name__)


class Intent(StrEnum):
    HANDOVER = "handover"
    """Must reach a person. Never answered, never guessed at."""

    CLARIFICATION_REPLY = "clarification_reply"
    """An answer to a question the assistant just asked."""

    SCOPING = "scoping"
    """Is this in scope, refused, local, or does it need a quote?"""

    BUDGET = "budget"
    QUOTE = "quote"

    ACTION = "action"
    """Asking the assistant to do something outside the chat, such as drafting
    a brief or raising a purchase order. Always proposed, never performed."""

    FOLLOW_UP = "follow_up"
    """A continuation that only makes sense against the previous turn."""

    CAPABILITIES = "capabilities"
    GREETING = "greeting"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class HandoverTopic:
    """A subject the assistant must not attempt."""

    name: str
    reason: str
    """Said to the user, so it is written for them rather than for a log."""


# Checked before every other intent. Each entry is a subject where a plausible
# machine answer is worse than no answer: it carries legal, safety or
# commercial consequences that a scoping tool has no standing to decide.
#
# The patterns lean specific on purpose. "Complaint" alone would swallow
# legitimate questions about review management, which is a service in the
# catalog and handled locally, so the trigger is the escalation around a
# complaint rather than the word itself.
HANDOVER_TOPICS: tuple[tuple[re.Pattern[str], HandoverTopic], ...] = (
    (
        re.compile(
            r"\b(injur\w*|accident|hurt|hospital|ambulance|casualt\w*|"
            r"safety incident|incident report)\b",
            re.IGNORECASE,
        ),
        HandoverTopic(
            "safety",
            "Anything involving an injury or a safety incident goes straight to your "
            "operations and safety leads, not through a marketing tool.",
        ),
    ),
    (
        re.compile(
            r"\b(lawsuit|sue|suing|solicitor|lawyer|legal action|liabilit\w*|"
            r"litigation|court|contract terms|breach of contract)\b",
            re.IGNORECASE,
        ),
        HandoverTopic(
            "legal",
            "Legal and contractual questions need your legal contact rather than a "
            "scoping assistant.",
        ),
    ),
    (
        re.compile(
            r"\b(gdpr|data subject|right to be forgotten|personal data|"
            r"data breach|delete (their|his|her|the customer'?s) data)\b",
            re.IGNORECASE,
        ),
        HandoverTopic(
            "data protection",
            "Data protection requests have their own process and a legal deadline, so "
            "they go to your data protection contact.",
        ),
    ),
    (
        re.compile(
            r"\b(journalist|press enquir\w*|press inquir\w*|media enquir\w*|"
            r"reporter|news crew|statement to the press)\b",
            re.IGNORECASE,
        ),
        HandoverTopic(
            "press",
            "Press enquiries are handled by your communications lead so that Acme "
            "speaks with one voice.",
        ),
    ),
    (
        re.compile(
            r"\b(refund|chargeback|compensat\w*|goodwill gesture|"
            r"threaten\w* to sue|escalat\w* complaint|formal complaint)\b",
            re.IGNORECASE,
        ),
        HandoverTopic(
            "customer resolution",
            "Refunds and formal complaints are a customer resolution decision, not a "
            "marketing one.",
        ),
    ),
    (
        re.compile(
            r"\b(discount|renegotiat\w*|commercial terms|rate reduction|"
            r"waive the fee|reduce the fee)\b",
            re.IGNORECASE,
        ),
        HandoverTopic(
            "commercial terms",
            "Changing what something costs is a commercial decision for your account "
            "and country leads.",
        ),
    ),
)

_BUDGET_RE = re.compile(
    r"\b("
    r"budget|spend|spent|remaining|left to spend|allocation|funds|"
    # "how much money do we have in the london branch" — money/funds before
    # have/do, so the older "how much (have|do) we" pattern never fired.
    r"how much (money|budget|spend|funds)|"
    r"how much (have|has|do|did) (we|they|i)|"
    r"(money|funds|budget).{0,48}\b(left|remaining|have|got)|"
    r"\bleft\b.{0,32}\b(branch|month|budget)|"
    r"underspend|overspend"
    r")\b",
    re.IGNORECASE,
)

# "what's left for london", "anything left at basingstoke" — a money question
# that never says the word money. Only trusted when a site or country is named,
# because "what's left" about a service is a scoping question.
_LEFT_RE = re.compile(
    r"\b(what'?s? left|anything left|much left|left to spend|how are we doing|"
    r"where are we (on|with)|how'?s the (budget|spend))\b",
    re.IGNORECASE,
)

_QUOTE_RE = re.compile(
    r"\b(quote|quotation|how much (would|will|does|is) .*(cost|be)|"
    r"what would .* cost|price for|cost of|ballpark|estimate)\b",
    re.IGNORECASE,
)

_ACTION_RE = re.compile(
    r"\b(send|email|draft|write up|raise a po|purchase order|forward|"
    r"let (them|him|her) know|chase|brief the|put in a request)\b",
    re.IGNORECASE,
)


_CAPABILITIES_RE = re.compile(
    r"\b("
    r"what can you (do|help)|what do you do|how do you work|"
    r"who are you|what are you|help me understand what|"
    # Catalog overview — must not fall through to scoping/retrieval.
    r"what (are|is) (our|the|your)?\s*services|"
    r"which services|"
    r"(list|show|tell me|give me) (me )?(all |our |the |your |a )?(list of )?(services|offerings)|"
    r"(a |the )?(full )?list of (all |the |our |your )?services|"
    r"services (do you|can you|we) (offer|cover|do|have)|"
    r"what (do|can) (you|we) (offer|cover)|"
    r"full (service )?list|"
    r"service (list|catalogue|catalog|breakdown)"
    r")\b",
    re.IGNORECASE,
)

_GREETING_RE = re.compile(
    r"^\s*(hi|hey|hello|morning|good morning|good afternoon|ok|okay|great|perfect)"
    r"\b[\s!.,]*$"
    # "thanks, that's great" is still a thank-you. Bounded so that "thanks, can
    # we do billboards" stays a scoping question.
    r"|^\s*(thanks|thank you|cheers|ta|nice one|brilliant|perfect)\b[\s\w',.!]{0,24}$",
    re.IGNORECASE,
)

_SCOPING_RE = re.compile(
    r"\b(can (we|you|i)|could (we|you|i)|are (we|you) able|is it possible|"
    r"do (we|you) (do|offer|cover|handle)|in scope|out of scope|covered|"
    r"included|who (does|handles|looks after|owns)|is that something|"
    r"i need|we need|i want|we want|looking for|help with)\b",
    re.IGNORECASE,
)

_FOLLOW_UP_RE = re.compile(
    r"^\s*(and |what about |how about |same for |also |then )",
    re.IGNORECASE,
)

_ORDINALS: dict[str, int] = {
    "first": 1, "1st": 1, "one": 1,
    "second": 2, "2nd": 2, "two": 2,
    "third": 3, "3rd": 3, "three": 3,
    "fourth": 4, "4th": 4, "four": 4,
}

MAX_TOKENS_FOR_A_BARE_FOLLOW_UP = 6
"""Longer than this and a message stands on its own, even if it opens with
"and". Carrying stale context into a fully formed question is worse than
ignoring it, because the user cannot see what was carried."""


@dataclass(frozen=True, slots=True)
class ConversationState:
    """What the previous turn left behind.

    Held by the caller and passed in, so the router stays a pure function and
    can be tested one message at a time.
    """

    pending_candidates: tuple[str, ...] = ()
    """Item ids the assistant just asked the user to choose between. Their
    presence changes how the next message is read, which is why the router
    needs them."""

    last_item_ids: tuple[str, ...] = ()
    last_branch: str | None = None
    last_intent: Intent | None = None
    conversation_id: str | None = None
    """Stable id for audit logging across client-carried turns."""

    pending_action_kind: str | None = None
    """``email_am`` / ``email_cm_po`` / ``email_am_variable`` while awaiting Yes/No."""

    pending_service_id: str | None = None
    pending_quote_amount: float | None = None
    pending_currency: str = "GBP"
    pending_recipient_country: str | None = None
    pending_recipient_name: str | None = None
    pending_needs_country: bool = False
    """True when the next turn should name a country before mail send."""

    active_tool: str | None = None
    """Sticky tool session, e.g. ``budget``, until a clear topic change."""

    budget_country: str | None = None
    budget_branch: str | None = None
    budget_month: str | None = None
    """Last resolved budget slots — reused on sticky follow-ups."""

    @property
    def awaiting_answer(self) -> bool:
        return bool(self.pending_candidates)

    @property
    def awaiting_action_confirm(self) -> bool:
        return bool(self.pending_action_kind)

    @property
    def budget_sticky(self) -> bool:
        return self.active_tool == "budget"


@dataclass(frozen=True, slots=True)
class Route:
    """Where a message should go, and why."""

    intent: Intent
    message: str
    matched: str | None = None
    """The text that triggered this route. Surfaced so a misrouted message can
    be diagnosed without guessing."""

    handover_topic: HandoverTopic | None = None
    selected_item_id: str | None = None
    """Which candidate the user picked, when answering a clarifying question."""

    carried_item_ids: tuple[str, ...] = field(default=())
    """Context inherited from the previous turn for a bare follow-up."""

    branch: str | None = None

    @property
    def needs_a_human(self) -> bool:
        return self.intent is Intent.HANDOVER

    def explain(self) -> str:
        detail = f" on {self.matched!r}" if self.matched else ""
        if self.handover_topic:
            return f"handover ({self.handover_topic.name}){detail}"
        if self.selected_item_id:
            return f"clarification reply{detail}: {self.selected_item_id}"
        if self.carried_item_ids:
            return f"{self.intent.value}{detail}, carrying {', '.join(self.carried_item_ids)}"
        return f"{self.intent.value}{detail}"


class Router:
    """Classifies a message into an intent.

    Safety gates (handover, confirmations) stay rule-based. Catalog inventory
    can also be recognised semantically so paraphrases do not need new regex.
    """

    def __init__(
        self,
        branches: Collection[str] = (),
        *,
        inventory_detector: Callable[[str], bool] | None = None,
    ) -> None:
        # Branch names arrive with the glossary document. Until then this is
        # empty and every route reports no branch, which is honest: the
        # assistant should ask rather than assume which site is meant.
        # Index by branch_key so "London" and "Acme London" resolve the same.
        self._branches = {branch_key(name): name for name in branches if name}
        self._inventory_detector = inventory_detector

    def route(self, message: str, state: ConversationState | None = None) -> Route:
        state = state or ConversationState()
        branch = self._find_branch(message)

        # Before anything else. A message can mention a service and an injury
        # in the same breath, and only one of those decides where it goes.
        if handover := self._find_handover_topic(message):
            trigger, topic = handover
            logger.info("router.handover", topic=topic.name, matched=trigger)
            return Route(
                Intent.HANDOVER,
                message,
                matched=trigger,
                handover_topic=topic,
                branch=branch,
            )

        if state.awaiting_answer and (
            selected := self._match_selection(message, state.pending_candidates)
        ):
            return Route(
                Intent.CLARIFICATION_REPLY,
                message,
                matched=message.strip(),
                selected_item_id=selected,
                branch=branch,
            )

        # Yes/No / country after a flow CTA. Checked before generic ACTION
        # keywords so a bare "Yes" or "United Kingdom" confirms rather than stubs.
        if state.awaiting_action_confirm:
            if state.pending_needs_country:
                return Route(Intent.ACTION, message, matched="country", branch=branch)
            # One yes/no vocabulary, shared with the flow that acts on it. When
            # these disagreed, a CTA could be routed here and then refuse to
            # fire, or fire on a message the flow never treated as consent.
            confirmed = is_affirmative(message)
            if confirmed is True:
                return Route(Intent.ACTION, message, matched="yes", branch=branch)
            if confirmed is False:
                return Route(Intent.ACTION, message, matched="no", branch=branch)

        # Inventory → full catalog tool (not top-k retrieval). Cheap patterns
        # first; semantic detector catches paraphrases when embeddings exist.
        if wants_service_list(message) or (
            self._inventory_detector is not None and self._inventory_detector(message)
        ):
            matched = (
                "service list"
                if wants_service_list(message)
                else "service list (semantic)"
            )
            return Route(Intent.CAPABILITIES, message, matched=matched, branch=branch)

        # Sticky budget session: keep chaining on the ledger until the user
        # clearly changes topic. Phrase lists do not scale; the session does.
        if state.budget_sticky and not _leaves_budget_sticky(message):
            route = Route(
                Intent.BUDGET,
                message,
                matched="sticky:budget",
                branch=branch or state.budget_branch or state.last_branch,
            )
            logger.info(
                "router.sticky",
                tool="budget",
                matched=route.matched,
                branch=route.branch,
                country=state.budget_country,
                month=state.budget_month,
            )
            return route

        for pattern, intent in (
            (_CAPABILITIES_RE, Intent.CAPABILITIES),
            (_BUDGET_RE, Intent.BUDGET),
            (_QUOTE_RE, Intent.QUOTE),
            (_ACTION_RE, Intent.ACTION),
        ):
            if keyword := pattern.search(message):
                route = Route(intent, message, matched=keyword.group(0), branch=branch)
                logger.info(
                    "router.classified",
                    intent=route.intent.value,
                    matched=route.matched,
                    branch=route.branch,
                )
                return route

        # A money question that never says "budget", saved by the site name.
        if branch is not None and (left := _LEFT_RE.search(message)):
            route = Route(Intent.BUDGET, message, matched=left.group(0), branch=branch)
            logger.info(
                "router.classified",
                intent=route.intent.value,
                matched=route.matched,
                branch=route.branch,
            )
            return route

        if _GREETING_RE.match(message):
            route = Route(Intent.GREETING, message, matched=message.strip(), branch=branch)
            logger.info("router.classified", intent=route.intent.value, matched=route.matched)
            return route

        if self._is_bare_follow_up(message, state):
            route = Route(
                Intent.FOLLOW_UP,
                message,
                matched=message.strip(),
                carried_item_ids=state.last_item_ids,
                branch=branch or state.last_branch,
            )
            logger.info(
                "router.classified",
                intent=route.intent.value,
                matched=route.matched,
                branch=route.branch,
            )
            return route

        if framing := _SCOPING_RE.search(message):
            route = Route(Intent.SCOPING, message, matched=framing.group(0), branch=branch)
            logger.info(
                "router.classified",
                intent=route.intent.value,
                matched=route.matched,
                branch=route.branch,
            )
            return route

        # A message naming a service without any framing is still a scoping
        # question. People type "billboards?" and mean "can you do billboards?"
        if content_tokens(message):
            route = Route(Intent.SCOPING, message, branch=branch)
            logger.info(
                "router.classified",
                intent=route.intent.value,
                matched=route.matched,
                branch=route.branch,
            )
            return route

        route = Route(Intent.UNKNOWN, message, branch=branch)
        logger.info("router.classified", intent=route.intent.value, matched=route.matched)
        return route

    @staticmethod
    def _find_handover_topic(message: str) -> tuple[str, HandoverTopic] | None:
        for pattern, topic in HANDOVER_TOPICS:
            if trigger := pattern.search(message):
                return trigger.group(0), topic
        return None

    def _find_branch(self, message: str) -> str | None:
        # Match longest key first so "milton keynes" wins over a hypothetical
        # shorter site that is a substring of another normalised form.
        normalized = normalize_term(message)
        for key, name in sorted(self._branches.items(), key=lambda item: -len(item[0])):
            # Keys are slugified (hyphens); message tokens are spaces.
            needle = key.replace("-", " ")
            if re.search(rf"\b{re.escape(needle)}\b", normalized):
                return name
            if branch_key(message) == key and len(normalized.split()) <= 4:
                # Bare "London" / "Milton Keynes" after "which branch?"
                return name
        return None

    @staticmethod
    def _match_selection(message: str, candidates: tuple[str, ...]) -> str | None:
        """Work out which option the user picked, if any.

        Returns ``None`` when the message is not an answer at all, because
        people change the subject mid-question and the alternative is
        answering a question they have abandoned.
        """
        normalized = normalize_term(message)
        if not normalized:
            return None

        # Naming a candidate is checked before counting, because "one" is both
        # a number and a filler word. In "the hoarding one" it means neither
        # first nor last, and reading it as an ordinal picked the wrong option.
        if tokens := set(content_tokens(message)):
            named = [
                item_id
                for item_id in candidates
                if tokens & set(content_tokens(item_id.replace("-", " ")))
            ]
            if named:
                # Naming several candidates at once, as "the photography one"
                # does when both are Photography, chooses none of them. Falling
                # through to counting would read the "one" as an ordinal and
                # silently answer about the first.
                return named[0] if len(named) == 1 else None

        for word in normalized.split():
            position = int(word) if word.isdigit() else _ORDINALS.get(word, 0)
            if 0 < position <= len(candidates):
                return candidates[position - 1]

        return None

    @staticmethod
    def _is_bare_follow_up(message: str, state: ConversationState) -> bool:
        if not state.last_item_ids:
            return False
        if len(content_tokens(message)) > MAX_TOKENS_FOR_A_BARE_FOLLOW_UP:
            return False
        return bool(_FOLLOW_UP_RE.match(message))


def _leaves_budget_sticky(message: str) -> bool:
    """True when the user has clearly left the budget tool session.

    Budget-keyword turns stay sticky even if they also match loose scoping
    framing ("can we check how much budget…").
    """
    if wants_service_list(message):
        return True
    if _CAPABILITIES_RE.search(message):
        return True
    if _QUOTE_RE.search(message):
        return True
    if _ACTION_RE.search(message):
        return True
    if _BUDGET_RE.search(message) or _LEFT_RE.search(message):
        return False
    return bool(_SCOPING_RE.search(message))
