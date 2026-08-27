"""Invariants for the catalog parser.

These hold for any corpus in this format. They are kept apart from the corpus
anchors in ``test_corpus_anchors.py`` on purpose: an invariant breaking means
the code is wrong, an anchor breaking usually means the documents changed.
"""

from __future__ import annotations

import pytest

from app.core.errors import MalformedDocumentError, UnknownStatusCodeError
from app.core.types import Status
from app.knowledge.catalog import ServiceCatalog, Severity, parse_service_document

WELL_FORMED = """\
# Billboards — Photography

**Section:** Photography
**Item:** Billboards
**Status code:** On demand
**Status meaning:** This is something we need to quote
**Also known as:** outdoor advertising, large format prints

## Summary
Billboards need a quote.

## What This Item Covers
Large-scale photographic displays.

## What the "On demand" Status Means for This Item
Handled case by case.

## At a Glance
- **In scope (included):** Conditional — quoted case by case
- **Delivered by:** the central marketing team
- **Extra cost or quote required:** Yes
- **What to do to get it:** Submit specifications

## Likely Questions
- Q: How do I get a quote? — A: Ask the central marketing team.
"""


def test_parses_a_well_formed_document_without_complaint() -> None:
    item, issues = parse_service_document(WELL_FORMED, "photography--billboards.md")

    assert issues == []
    assert item.item_id == "photography--billboards"
    assert item.status is Status.QUOTE_REQUIRED
    assert item.status.requires_quote
    assert item.aliases == ("outdoor advertising", "large format prints")
    assert item.at_a_glance.extra_cost_or_quote == "Yes"
    assert item.summary == "Billboards need a quote."
    assert set(item.sections) >= {"Summary", "At a Glance", "Likely Questions"}
    # The fifth bullet is optional, and its absence must not be reported as a
    # defect the way a missing required bullet is.
    assert item.at_a_glance.automatic_price is None


def test_the_optional_automatic_price_bullet_is_read_when_present() -> None:
    text = WELL_FORMED.replace(
        "- **What to do to get it:** Submit specifications",
        "- **What to do to get it:** Submit specifications\n"
        "- **Automatic price:** No — third-party costs dominate",
    )
    item, issues = parse_service_document(text, "photography--billboards.md")

    assert issues == []
    assert item.at_a_glance.automatic_price == "No — third-party costs dominate"


@pytest.mark.parametrize("raw", ["Y", "y", " Y ", "Y  "])
def test_status_whitespace_and_case_are_formatting_not_meaning(raw: str) -> None:
    assert Status.from_raw_code(raw, source="test.md") is Status.IN_SCOPE


@pytest.mark.parametrize("raw", ["Maybe", "", "YES", "on-demand"])
def test_an_unrecognised_status_is_fatal_rather_than_defaulted(raw: str) -> None:
    """The whole system rests on this. A guessed default could price a paid
    service at zero, which is the one mistake that must never reach a user."""
    with pytest.raises(UnknownStatusCodeError):
        Status.from_raw_code(raw, source="test.md")


def test_stray_whitespace_in_a_status_is_reported_but_not_fatal() -> None:
    document = WELL_FORMED.replace("**Status code:** On demand", "**Status code:** On demand  ")
    item, issues = parse_service_document(document, "photography--billboards.md")

    assert item.status is Status.QUOTE_REQUIRED
    assert any("whitespace" in issue.message for issue in issues)
    assert all(issue.severity is Severity.WARNING for issue in issues)


@pytest.mark.parametrize("missing", ["**Section:** Photography", "**Item:** Billboards"])
def test_a_document_that_cannot_be_identified_raises(missing: str) -> None:
    with pytest.raises(MalformedDocumentError):
        parse_service_document(WELL_FORMED.replace(missing, ""), "broken.md")


def test_missing_sections_are_reported_individually() -> None:
    document = WELL_FORMED.replace("## Likely Questions", "## Something Else")
    _, issues = parse_service_document(document, "photography--billboards.md")

    assert any("likely questions" in issue.message for issue in issues)


def test_a_truncated_filename_is_reported() -> None:
    _, issues = parse_service_document(WELL_FORMED, "photography--bill.md")

    assert any("filename does not match" in issue.message for issue in issues)


def test_casing_differences_between_title_and_item_are_not_reported() -> None:
    """Presentation, not a discrepancy. Reporting it would bury real problems."""
    document = WELL_FORMED.replace("# Billboards — Photography", "# BILLBOARDS — Photography")
    _, issues = parse_service_document(document, "photography--billboards.md")

    assert not any("does not name the Item" in issue.message for issue in issues)


def test_a_genuinely_different_title_is_reported() -> None:
    document = WELL_FORMED.replace("# Billboards — Photography", "# Hoardings — Photography")
    _, issues = parse_service_document(document, "photography--billboards.md")

    assert any("does not name the Item" in issue.message for issue in issues)


def test_alias_index_preserves_ambiguity_instead_of_overwriting() -> None:
    """Two items sharing an alias is normal in this domain. The index must keep
    both so the resolver can ask which is meant."""
    first, _ = parse_service_document(WELL_FORMED, "photography--billboards.md")
    second, _ = parse_service_document(
        WELL_FORMED.replace("**Item:** Billboards", "**Item:** Hoarding"),
        "photography--hoarding.md",
    )
    catalog = ServiceCatalog.build([first, second])

    matches = catalog.lookup_phrase("outdoor advertising")
    assert {item.item_id for item in matches} == {
        "photography--billboards",
        "photography--hoarding",
    }


def test_lookup_is_insensitive_to_how_a_user_types_the_phrase() -> None:
    item, _ = parse_service_document(WELL_FORMED, "photography--billboards.md")
    catalog = ServiceCatalog.build([item])

    for phrasing in ("Billboards", "billboards", "  BILLBOARDS  "):
        assert catalog.lookup_phrase(phrasing)[0].item_id == "photography--billboards"
