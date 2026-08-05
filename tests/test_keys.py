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


def test_magazines_does_not_over_stem() -> None:
    """Regression. A bare 'es' rule turned 'magazines' into 'magazin' while a
    query for 'magazine' stayed whole, so the two never matched and the
    Photography item lost to an unrelated one."""
    assert stem("magazines") == "magazine"


def test_double_s_words_are_left_alone() -> None:
    assert stem("class") == "class"
    assert stem("classes") == "class"


def test_short_words_are_never_stemmed() -> None:
    for word in ("ads", "seo", "is", "gas"):
        assert stem(word) == word


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
