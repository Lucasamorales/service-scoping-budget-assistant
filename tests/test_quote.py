"""Quote rate card parsing — tiers 1/2/3 only; optional Sheets overlay."""

from __future__ import annotations

from pathlib import Path

from app.store.quote import _parse_pricing_tier_rows, load_quote_store


def test_fixture_rate_card_has_three_numeric_tiers() -> None:
    store = load_quote_store(Path("fixtures/quote/rate_card.json"))
    assert store is not None
    assert set(store.tiers) >= {"1", "2", "3", "Variable"}
    assert "4" not in store.tiers
    assert store.tiers["1"] == 100.0
    assert store.tiers["2"] == 200.0
    assert store.tiers["3"] == 350.0


def test_pricing_tier_sheet_rows_parse() -> None:
    rows = [
        ["Tier", "Price"],
        ["Tier 1", 100],
        ["Tier 2", 200],
        ["Tier 3", 350],
    ]
    assert _parse_pricing_tier_rows(rows) == {"1": 100.0, "2": 200.0, "3": 350.0}


def test_merch_maps_to_tier_one() -> None:
    store = load_quote_store(Path("fixtures/quote/rate_card.json"))
    assert store is not None
    looked = store.lookup(
        "renders-and-other-designs-for-venue-exteriors--merch"
    )
    assert looked == ("1", 100.0)
