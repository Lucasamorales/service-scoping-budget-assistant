"""Facts about the corpus as it stands today, each verified by reading the source.

These are anchors, not invariants. They will break when the service breakdown
changes, and that is correct behaviour: re-verify against the new documents and
update the number, rather than deleting the assertion. An anchor that gets
deleted the first time it fails was never protecting anything.

The gate at the top is different. It must never be relaxed.
"""

from __future__ import annotations

from collections import Counter

from app.core.types import Status
from app.knowledge.catalog import CatalogLoadResult

EXPECTED_ITEM_COUNT = 81
EXPECTED_SECTION_COUNT = 10
EXPECTED_STATUS_COUNTS = {
    Status.IN_SCOPE: 40,
    Status.QUOTE_REQUIRED: 21,
    Status.LOCAL: 16,
    Status.OUT_OF_SCOPE: 4,
}


def test_the_corpus_loads_without_a_single_error(corpus: CatalogLoadResult) -> None:
    """The gate. An error means some verdict cannot be trusted."""
    assert corpus.errors == (), "\n".join(str(issue) for issue in corpus.errors)


def test_the_corpus_is_actually_loaded(corpus: CatalogLoadResult) -> None:
    """A smoke test that can silently pass over an empty corpus is worse than
    no smoke test at all."""
    assert len(corpus.catalog) == EXPECTED_ITEM_COUNT


def test_every_status_is_represented(corpus: CatalogLoadResult) -> None:
    counts = Counter(item.status for item in corpus.catalog)
    assert dict(counts) == EXPECTED_STATUS_COUNTS


def test_section_count(corpus: CatalogLoadResult) -> None:
    assert len(corpus.catalog.sections()) == EXPECTED_SECTION_COUNT


def test_known_verdicts(corpus: CatalogLoadResult) -> None:
    """One item per status, spot-checked against the document it came from."""
    expected = {
        "photography--billboards": Status.QUOTE_REQUIRED,
        "copywriting--emails": Status.IN_SCOPE,
        "strategic-support--landlord-relationship": Status.LOCAL,
        "strategic-support--occupancy-calls": Status.OUT_OF_SCOPE,
    }
    for item_id, status in expected.items():
        assert corpus.catalog.require(item_id).status is status


def test_all_photography_needs_a_quote(corpus: CatalogLoadResult) -> None:
    photography = [item for item in corpus.catalog if item.section == "Photography"]
    assert len(photography) == 8
    assert all(item.status.requires_quote for item in photography)


def test_all_organic_social_is_handled_locally(corpus: CatalogLoadResult) -> None:
    social = [
        item
        for item in corpus.catalog
        if item.section == "Organic social media and community management"
    ]
    assert len(social) == 10
    assert all(item.status is Status.LOCAL for item in social)


def test_every_item_carries_the_domains_own_wording_for_its_verdict(
    corpus: CatalogLoadResult,
) -> None:
    """The assistant explains a verdict using the corpus's phrasing, so every
    item has to have some."""
    assert all(item.status_meaning for item in corpus.catalog)


def test_every_item_is_reachable_by_at_least_one_alias(corpus: CatalogLoadResult) -> None:
    for item in corpus.catalog:
        assert item.aliases, f"{item.source} has no aliases"


def test_the_known_ambiguous_phrases(corpus: CatalogLoadResult) -> None:
    """Genuine domain overlaps the resolver has to disambiguate rather than guess.

    'video post production' spanning three items across two sections is the
    clearest example of why a similarity score must not pick the verdict.
    """
    ambiguous = {
        term: len(ids) for term, ids in corpus.catalog.alias_index.items() if len(ids) > 1
    }
    assert ambiguous == {
        "billboards": 2,
        "content planning": 3,
        "editorial calendar": 2,
        "outdoor advertising": 2,
        "strategic marketing meetings": 2,
        "video post production": 3,
        "visual content": 2,
    }
