"""Canonical key and normalisation functions.

Every entity that crosses a module boundary is identified by a key produced
here, and nowhere else. Identity bugs of the ``"Chapter 2"`` versus
``"Chapter 2: title"`` kind are silent: a lookup returns nothing, a counter
stays at zero, and no error is ever logged. One shared implementation is the
only reliable defence.

Two distinct normalisations live here and must not be confused:

``slugify``
    Produces stable identifiers. Punctuation is dropped, so ``"Design &
    creative"`` becomes ``design-creative``. This matches the convention the
    corpus filenames already follow.

``normalize_term``
    Produces text for alias matching. Punctuation becomes meaningful
    whitespace and ``&`` expands to ``and``, so a user typing "design and
    creative" matches an item titled "Design & creative".
"""

from __future__ import annotations

import re
import threading
import unicodedata
from functools import lru_cache
from typing import Any

import snowballstemmer

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
_WHITESPACE = re.compile(r"\s+")

# Brand prefixes carry no information for branch identity, and users drop them
# freely: "Acme Manchester", "Manchester" and "manchester" are one branch.
_BRANCH_BRAND_PREFIXES = ("acme", "i fly")


def strip_accents(text: str) -> str:
    """Fold accented characters onto their ASCII base."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def slugify(text: str) -> str:
    """Reduce arbitrary text to a lowercase hyphenated identifier."""
    folded = strip_accents(text).lower()
    return _NON_ALPHANUMERIC.sub("-", folded).strip("-")


def normalize_term(text: str) -> str:
    """Reduce text to a comparable form for alias and keyword matching."""
    folded = strip_accents(text).lower().replace("&", " and ")
    spaced = _NON_ALPHANUMERIC.sub(" ", folded)
    return _WHITESPACE.sub(" ", spaced).strip()


def tokenize(text: str) -> tuple[str, ...]:
    """Split text into normalised tokens, unstemmed and including stopwords."""
    normalized = normalize_term(text)
    return tuple(normalized.split()) if normalized else ()


# Snowball's English stemmer, in place of the hand-written suffix rules this
# module used to carry.
#
# Those rules were replaced rather than extended because the words they missed
# had nothing in common. A request to "schedule" our posts never reached the
# item named "Content scheduling", because stripping "-ing" leaves "schedul"
# while the bare verb keeps its silent "-e" — and that answered a Local item as
# in-scope and free of charge. The same gap sat under plan/planning,
# manage/management and quote/quoting, and each one needs a different rule:
# restore an "e", collapse a doubled consonant, strip "-ment". Hand-written
# rules meant one new rule per defect found in production, and this is a class
# of defect users find rather than tests.
#
# Snowball is pure Python with no data files, so it costs the image nothing.
#
# The stemmer holds mutable cursor state on the instance, so it cannot be
# shared between threads — uvicorn runs sync handlers in a threadpool. One
# instance per thread, with the results memoised in front of it: stemming is
# deterministic, so a cache hit from another thread is still correct, and the
# corpus vocabulary is small enough that almost every call is a hit.
_local = threading.local()


def _stemmer() -> Any:
    stemmer = getattr(_local, "stemmer", None)
    if stemmer is None:
        stemmer = _local.stemmer = snowballstemmer.stemmer("english")
    return stemmer


# Removed before scoring rather than left to inverse document frequency. These
# words appear inside item names, where they would collect the full hint weight
# and let "report ... from GA4" outrank a better match on the strength of
# "from".
STOPWORDS: frozenset[str] = frozenset(
    """
    a an the and or but if then than that this these those of in on at to for from by with
    without into onto over under again further here there all any both each few more most
    other some such no nor not only own same so too very can will just should now
    i we you he she it they them our your their us me my up
    is are was were be been being am do does did doing have has had having would could
    need needs needed want wants like get gets got make makes made please help
    who what when where why how which whose whom whether
    yes yeah yep no nope ok okay okey sure thanks thank cheers maybe perhaps sorry
    one two three four five first second third fourth fifth last next another
    """.split()  # noqa: SIM905  prose reads and edits better than a hundred quoted entries
)
"""Words that carry no signal about *which service* is meant.

The last two lines are the ones that earn their place. Conversational filler
and ordinals arrive constantly - people answer a clarifying question with "the
first one" - and they are not evidence of anything. Left in, "one" was rare
enough across 81 documents to score 12 on its own and won a confident verdict
for an unrelated email item, because a one-word query concentrates all of the
length-normalised score onto a single term.

Digits are deliberately absent: "4-5 per month" and "every 6 months" appear in
item names, so numerals do distinguish services even though number *words* do
not. Ordinals are safe to drop because the router reads them from the raw text
before tokenisation, so "the second one" still selects the second option.

"up" is here despite appearing in the item name "Monthly marketing catch ups",
which is the one case where a stopword costs an item some hint weight. It earns
its place anyway: as a phrasal particle it attaches to whatever verb precedes
it, so "can we **set up** a regular call about occupancy" matched the catch-ups
item on "up" and outscored the item actually named in the sentence. The
catch-ups item is still reached by "catch", "monthly" and "group", and a test
asserts that; nothing is reached by "up".
"""


@lru_cache(maxsize=8192)
def stem(token: str) -> str:
    """Reduce a token to its stem, so inflected forms of a word match.

    The stem is not a word and does not need to be: "translation" and
    "translate" both reduce to "translat", which is meaningless in isolation
    and exactly right as a key, because the same reduction runs over the
    corpus and over the query.

    Bounded cache because this is called on arbitrary user text as well as on
    the corpus, and an unbounded one would grow with traffic.
    """
    return str(_stemmer().stemWord(token))


# Words this industry uses interchangeably but which no suffix rule will ever
# unify, because they are abbreviations rather than inflections. A request
# saying "advert" was missing an item named "Video editing for ads" entirely.
#
# Kept deliberately short. Every entry asserts that two words mean the same
# thing here, and a wrong entry merges two services that should stay apart.
_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("ad", "ads", "advert", "adverts", "advertisement", "advertisements", "advertising"),
    ("photo", "photos", "photograph", "photographs", "photography", "photographic"),
    ("email", "emails", "e-mail", "e-mails", "mailer", "mailers"),
    ("logo", "logos", "branding", "brand"),
)

_SYNONYMS: dict[str, str] = {
    stem(variant): stem(group[0]) for group in _SYNONYM_GROUPS for variant in group
}


def canonical_token(token: str) -> str:
    """Stem a word, then fold it onto the industry's preferred spelling."""
    stemmed = stem(token)
    return _SYNONYMS.get(stemmed, stemmed)


# "ad hoc" is not an advertisement. Left alone, folding "ad" onto the advert
# family made a request about an advert match an item named "Video editing ad
# hoc". Joined into one word before tokenising so the two never meet.
_AD_HOC_RE = re.compile(r"\bad[ -]+hoc\b")


def content_tokens(text: str) -> tuple[str, ...]:
    """The tokeniser retrieval scores on: normalised, stopword-free, stemmed
    and folded onto canonical industry vocabulary."""
    normalized = _AD_HOC_RE.sub("adhoc", normalize_term(text))
    return tuple(
        canonical_token(token) for token in normalized.split() if token not in STOPWORDS
    )


def service_key(section: str, item: str) -> str:
    """Build the canonical identifier for a service catalog entry.

    Derived from the ``Section`` and ``Item`` fields inside the document rather
    than from its filename, because at least one filename in the corpus is
    truncated and no longer reflects the item it contains.
    """
    return f"{slugify(section)}--{slugify(item)}"


def branch_key(text: str) -> str:
    """Build the canonical identifier for a branch.

    The branch glossary is not yet part of the corpus. When it lands it will
    supply the alias table, but every alias will resolve through this function,
    so branch identity stays decided in exactly one place.
    """
    normalized = normalize_term(text)
    for prefix in _BRANCH_BRAND_PREFIXES:
        if normalized.startswith(f"{prefix} "):
            normalized = normalized[len(prefix) :].strip()
            break
    return slugify(normalized)
