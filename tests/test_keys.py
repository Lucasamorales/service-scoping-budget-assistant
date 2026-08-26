"""Invariants for the canonical key functions.

These hold for any corpus. Identity bugs are silent, so the distinction
between the two normalisations is pinned here deliberately.
"""

from __future__ import annotations

import pytest

from app.core.keys import (
    STOPWORDS,
    content_tokens,
    normalize_term,
    service_key,
    slugify,
    stem,
    tokenize,
    branch_key,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Design & creative", "design-creative"),
        ("SEO/AIO", "seo-aio"),
        (
            "Ad hoc email requests (typically 4-5 per month)",
            "ad-hoc-email-requests-typically-4-5-per-month",
        ),
        ("  padded  ", "padded"),
        ("Café", "cafe"),
    ],
)
def test_slugify_matches_the_corpus_filename_convention(text: str, expected: str) -> None:
    assert slugify(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Design & creative", "design and creative"),
        ("SEO/AIO", "seo aio"),
        ("Posters, leaflets & flyer designs", "posters leaflets and flyer designs"),
    ],
)
def test_normalize_term_expands_punctuation_for_matching(text: str, expected: str) -> None:
    assert normalize_term(text) == expected


def test_the_two_normalisations_are_not_interchangeable() -> None:
    """slugify is for identity, normalize_term is for matching. Never swap them."""
    assert slugify("Design & creative") != normalize_term("Design & creative")


def test_ampersand_and_the_word_and_match_each_other() -> None:
    assert normalize_term("Email marketing & SMS") == normalize_term("email marketing and sms")


def test_service_key_keeps_the_section_separator_distinct() -> None:
    key = service_key("Photography", "Billboards")
    assert key == "photography--billboards"
    # The double hyphen is load bearing: it is what separates section from
    # item, and re-slugifying a key would collapse it.
    assert slugify(key) != key


def test_branch_key_ignores_the_brand_prefix() -> None:
    assert branch_key("Acme Manchester") == branch_key("Manchester") == "manchester"


def test_branch_key_folds_case_and_spacing() -> None:
    assert branch_key("  MANCHESTER ") == "manchester"


def test_tokenize_drops_empty_tokens() -> None:
    assert tokenize("  video   editing  ") == ("video", "editing")
    assert tokenize("") == ()


@pytest.mark.parametrize(
    "singular",
    ["leaflet", "billboard", "audit", "visit", "influencer", "calendar", "magazine", "newspaper"],
)
def test_a_plural_stems_to_its_singular(singular: str) -> None:
    """Plural mismatch was the single largest cause of retrieval misses:
    documents say 'leaflets' and users type 'leaflet'."""
    assert stem(f"{singular}s") == stem(singular)


@pytest.mark.parametrize(
    "singular",
    ["magazine", "template", "guideline", "package", "site", "image"],
)
def test_a_plural_of_a_word_ending_in_e_still_matches(singular: str) -> None:
    """Regression, and the reason this asserts a pair rather than a spelling.

    An earlier hand-written rule turned "magazines" into "magazin" while a
    query for "magazine" stayed whole, so the two never matched and the
    Photography item lost to an unrelated one. What matters is that both sides
    reduce to the *same* key; which key is an implementation detail of
    whichever stemmer is in use.
    """
    assert stem(f"{singular}s") == stem(singular)


def test_double_s_words_are_left_alone() -> None:
    assert stem("class") == "class"
    assert stem("classes") == "class"


def test_acronyms_and_product_names_survive_stemming() -> None:
    """This domain identifies services by short proper nouns, and a stemmer
    that mangled them would make the items that carry them unreachable."""
    for word in ("seo", "sms", "ga4", "qr", "tv", "gas", "is"):
        assert stem(word) == word, word


def test_stemming_is_idempotent() -> None:
    """A stem must survive being stemmed again, or corpus and query drift apart
    whenever one side is processed twice."""
    for word in ("leaflets", "magazines", "translation", "planning", "classes"):
        assert stem(stem(word)) == stem(word)


def test_content_tokens_removes_stopwords_and_stems() -> None:
    assert content_tokens("can we get a leaflet for the new classes") == (
        "leaflet",
        "new",
        "class",
    )


def test_question_words_are_stopwords() -> None:
    """They appear inside item names, where they would collect full hint weight
    and let an irrelevant item win on the strength of 'when' or 'who'."""
    for word in ("who", "what", "when", "where", "why", "how", "which"):
        assert word in STOPWORDS


def test_content_tokens_survives_an_all_stopword_query() -> None:
    assert content_tokens("can we do it") == ()


# Gerunds this corpus uses inside item names, paired with the verb a person
# would type instead. Curated rather than derived: stripping "-ing" gives
# "schedul" and "sourc", which are not words anyone types, so a mechanical
# rule would assert something weaker than the thing that actually broke.
#
# Every pair here failed before the stemmer was replaced. "Can central team
# schedule our Instagram posts?" never reached the item named "Content
# scheduling", and answered a Local service as in scope and free of charge.
_GERUND_AND_VERB = {
    "advertising": "advertise",
    "editing": "edit",
    "including": "include",
    "liaising": "liaise",
    "marketing": "market",
    "planning": "plan",
    "posting": "post",
    "reporting": "report",
    "reposting": "repost",
    "scheduling": "schedule",
    "sourcing": "source",
}


_NOUNS_THAT_LOOK_LIKE_GERUNDS = frozenset(
    {
        # A construction hoarding is a surface to print on, not the act of
        # hoarding. Nobody asks for one by saying "hoard".
        "hoarding",
        # "landing page" and "pre-existing" are compounds; neither half is a
        # verb somebody would substitute.
        "landing",
        "pre-existing",
    }
)
"""Words ending in -ing that name a thing rather than an action.

Listed so the coverage test stays a real gate. Pairing these with a verb would
assert something false — that a request to "hoard" means the Hoarding item."""


@pytest.mark.parametrize(("gerund", "verb"), sorted(_GERUND_AND_VERB.items()))
def test_a_gerund_and_its_verb_share_a_stem(gerund: str, verb: str) -> None:
    """The corpus names services with gerunds; people ask with verbs.

    This is the invariant behind the worst defect the golden-question round
    found, and it is asserted on the tokeniser rather than through retrieval
    so that a failure names the cause instead of a symptom.
    """
    assert stem(gerund) == stem(verb), f"{gerund} and {verb} must reduce to one key"


def test_every_gerund_in_the_corpus_is_covered(corpus) -> None:
    """Keeps the table above honest.

    Adding a service whose name contains a new gerund fails here until the
    verb people would use for it is written down — which is the point at which
    it is cheap to notice, rather than after somebody is told the wrong price.
    """
    found = {
        word.strip("()/,")
        for item in corpus.catalog
        for word in item.item.lower().replace("/", " ").split()
        if word.strip("()/,").endswith("ing") and len(word.strip("()/,")) > 6
    }
    missing = found - set(_GERUND_AND_VERB) - _NOUNS_THAT_LOOK_LIKE_GERUNDS
    assert not missing, f"add these to _GERUND_AND_VERB with the verb people type: {missing}"
