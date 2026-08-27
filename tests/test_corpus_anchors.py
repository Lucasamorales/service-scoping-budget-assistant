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

EXPECTED_ITEM_COUNT = 89
EXPECTED_SECTION_COUNT = 12
EXPECTED_STATUS_COUNTS = {
    Status.IN_SCOPE: 42,
    Status.QUOTE_REQUIRED: 25,
    Status.LOCAL: 18,
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


def _shared_aliases(corpus: CatalogLoadResult) -> dict[str, set[str]]:
    """Aliases more than one item declares, mapped to the verdicts they span."""
    return {
        term: {corpus.catalog.require(item_id).status.value for item_id in ids}
        for term, ids in corpus.catalog.alias_index.items()
        if len(ids) > 1
    }


def test_the_known_ambiguous_phrases(corpus: CatalogLoadResult) -> None:
    """Aliases that span *disagreeing* verdicts, pinned deliberately.

    These are the genuine domain overlaps the resolver has to put to the user
    rather than guess at, and adding one is a corpus authoring decision that
    deserves a second pair of eyes: "video post production" spanning three
    items across two sections is the clearest example of why a similarity
    score must not pick the verdict.

    An alias shared by items that *agree* is harmless and deliberately not
    listed — whichever one a request means, the answer is the same. That is
    what lets the platform names be declared on every Organic social item
    without turning each of them into a question.
    """
    disagreeing = {
        term: sorted(verdicts)
        for term, verdicts in _shared_aliases(corpus).items()
        if len(verdicts) > 1
    }
    assert disagreeing == {
        "content planning": ["in_scope", "local"],
        "editorial calendar": ["in_scope", "local"],
        "video post production": ["in_scope", "quote_required"],
    }


_KNOWN_FREE_VERSUS_CHARGEABLE = {
    # Editing footage the venue already has is in scope; producing a video for
    # a campaign is quoted. The phrase honestly covers both, which is why the
    # resolver's job here is to ask rather than to rank.
    "video post production",
}


def test_no_new_alias_spans_a_free_and_a_chargeable_item(
    corpus: CatalogLoadResult,
) -> None:
    """The overlap that costs money, kept separate from the ones that do not.

    Two items disagreeing about *who does it* costs a clarifying question. Two
    disagreeing about whether it is free is the error this product exists to
    prevent, and an alias is how they get quietly connected — it is a phrase
    somebody wrote in a document, not something anybody reviewed against the
    rest of the corpus.

    One such alias exists and is handled. This fails on a second, so adding it
    is a decision rather than an accident.
    """
    offenders = {
        term
        for term, verdicts in _shared_aliases(corpus).items()
        if {"in_scope", "quote_required"} <= verdicts
    }
    assert offenders <= _KNOWN_FREE_VERSUS_CHARGEABLE, (
        "new alias(es) spanning free and chargeable items: "
        f"{sorted(offenders - _KNOWN_FREE_VERSUS_CHARGEABLE)}"
    )
