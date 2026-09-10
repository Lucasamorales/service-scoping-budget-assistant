"""Quote rate card: tier parsing, the Scope service-to-tier map, drift, and
the per-document opt-out from automatic pricing."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from app.core.keys import service_key
from app.core.types import AtAGlance, ServiceItem, Status
from app.store.quote import (
    CachedQuoteStore,
    QuoteStore,
    _parse_pricing_tier_rows,
    _parse_scope_rows,
    load_quote_store,
)
from app.store.sheets_client import REFRESH_WAIT_SECONDS
from app.tools.quote import quote_for


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


def test_merch_prices_at_the_tier_the_sheet_says() -> None:
    """Regression guard on the drift bug.

    The fixture used to map Merch to Tier 1 and quote £100 for a £350 service,
    because the mapping was maintained by hand while the sheet moved on. The
    number below is the sheet's; refresh with ``scripts/refresh_rate_card.py``
    rather than editing it here.
    """
    store = load_quote_store(Path("fixtures/quote/rate_card.json"))
    assert store is not None
    assert store.lookup("renders-and-other-designs-for-venue-exteriors--merch") == ("3", 350.0)


def test_every_priced_service_is_a_real_catalog_item(corpus) -> None:
    """A tier for a service no document answers to prices nothing.

    This is the general form of the bug above: the sheet and the corpus can
    each be internally consistent and still disagree about what a service is
    called, and the symptom is a silent absence rather than an error.
    """
    store = load_quote_store(Path("fixtures/quote/rate_card.json"))
    assert store is not None
    unknown = sorted(set(store.services) - corpus.catalog.item_ids)
    assert not unknown, f"rate card prices items the corpus does not have: {unknown}"


def test_scope_rows_read_only_on_demand_items() -> None:
    """Yes and Local services are free; carrying a tier for one would price it."""
    rows: list[list[object]] = [
        ["section", "item", "status", "Tier"],
        ["Events", "Videos", "On demand", "Tier 3"],
        ["Events", "Planning", "Y", ""],
        ["Design & creative", "Logos", "Local", "Tier 2"],
    ]
    assert _parse_scope_rows(rows) == {service_key("Events", "Videos"): "3"}


def test_scope_rows_drop_an_unusable_tier() -> None:
    """Tier 4 was removed from the business's pricing. A leftover row naming it
    must not be guessed into a neighbouring tier."""
    rows: list[list[object]] = [
        ["Events", "Videos", "On demand", "Tier 4"],
        ["Events", "Photoshoots", "On demand", "Tier 2"],
    ]
    assert _parse_scope_rows(rows) == {service_key("Events", "Photoshoots"): "2"}


def _item(automatic_price: str | None) -> ServiceItem:
    return ServiceItem(
        item_id="events--attendance-travel-accommodation-food",
        section="Events",
        item="Attendance (travel, accommodation, food)",
        status=Status.QUOTE_REQUIRED,
        status_raw="On demand",
        status_meaning="This is something we need to quote",
        aliases=(),
        at_a_glance=AtAGlance(automatic_price=automatic_price),
        summary="",
        sections={},
        body="",
        source="events--attendance-travel-accommodation-food.md",
    )


def _store() -> QuoteStore:
    return QuoteStore(
        currency="GBP",
        tiers={"3": 350.0, "Variable": "Variable"},
        services={"events--attendance-travel-accommodation-food": "3"},
    )


def test_a_document_can_refuse_an_automatic_price() -> None:
    """The Scope tab tiers attendance at 3, but the bill is travel and hotels.

    Quoting £350 would understate it without bound, so the document opts out
    and the turn routes to a human instead.
    """
    outcome = quote_for(_item("No — travel and hotel costs dominate"), _store(), None)
    assert outcome.kind == "variable"
    assert "350" not in outcome.text


def test_a_tier_is_quoted_when_the_document_stays_silent() -> None:
    """Absence of the bullet means consent; the tier exists to be used."""
    outcome = quote_for(_item(None), _store(), None)
    assert outcome.kind != "variable"
    assert "350" in outcome.text


def test_an_affirmative_automatic_price_still_quotes() -> None:
    outcome = quote_for(_item("Yes"), _store(), None)
    assert outcome.kind != "variable"
    assert "350" in outcome.text


class TestCachedRateCard:
    """The sheet moving under a long-lived process.

    The static store is loaded once, which was correct while the tier map lived
    in a file. Now the business owns it on the sheet, so a reprice must not
    wait for the container to recycle.
    """

    @staticmethod
    def _card(price: float) -> QuoteStore:
        return QuoteStore(
            currency="GBP",
            tiers={"3": price, "Variable": "Variable"},
            services={"events--photoshoots": "3"},
        )

    def test_a_reprice_reaches_the_person_who_triggered_the_refresh(self) -> None:
        """Not the one after them.

        A purely background refresh served the card it was replacing, so the
        question that noticed the staleness got the old price and only the next
        one got the new. On a quiet service that gap is not seconds: nothing
        else touches the data, so production was found holding figures 38.7
        hours old.
        """
        cards = [self._card(400.0)]
        store = CachedQuoteStore(
            lambda: cards.pop(0) if cards else None,
            ttl_seconds=300,
            initial=self._card(350.0),
        )
        assert store.lookup("events--photoshoots") == ("3", 350.0)

        store._tried_at -= 301  # the TTL lapsing, without waiting it out

        assert store.lookup("events--photoshoots") == ("3", 400.0)

    def test_a_slow_sheet_does_not_block_the_answer(self) -> None:
        """The regression that took a live turn down.

        A billboard question arrived just as the TTL expired, the refresh ran
        inside the request, the Sheets read hung, and Cloud Run killed the turn
        at sixty seconds — the user watched it stop after "Looking that up...".
        """
        release = threading.Event()

        def slow() -> QuoteStore | None:
            release.wait(30)
            return self._card(400.0)

        store = CachedQuoteStore(slow, ttl_seconds=1, initial=self._card(350.0))
        store._tried_at -= 5

        started = time.monotonic()
        answer = store.lookup("events--photoshoots")
        elapsed = time.monotonic() - started
        release.set()

        assert elapsed < REFRESH_WAIT_SECONDS + 1.0, "the quote hung on the spreadsheet"
        assert answer == ("3", 350.0), "the card already in hand is served meanwhile"

    def test_a_failed_refresh_keeps_the_last_good_card(self) -> None:
        """A five-minute-old price beats no price, and beats a wrong one."""

        def explode() -> QuoteStore | None:
            raise RuntimeError("sheet unreachable")

        store = CachedQuoteStore(explode, ttl_seconds=300, initial=self._card(350.0))
        store._refresh()
        assert store.lookup("events--photoshoots") == ("3", 350.0)

    def test_an_unreadable_sheet_does_not_wipe_the_prices(self) -> None:
        """The loader returns None when the sheet cannot be read, and that must
        leave the card alone.

        This is what actually happened in production: the read timed out, the
        old code answered with a card carrying no numeric tiers, and the cache
        accepted it — so a transient timeout turned every priceable service
        into one the assistant could not price.
        """
        store = CachedQuoteStore(
            lambda: None, ttl_seconds=300, initial=self._card(350.0)
        )
        store._refresh()

        assert store.lookup("events--photoshoots") == ("3", 350.0)
        assert store.tiers["3"] == 350.0

    def test_age_keeps_growing_while_refreshes_fail(self) -> None:
        """The bug this guards: one clock for both 'when did we last read' and
        'when did we last try' made a failing refresh reset the age to zero, so
        data that was getting older looked permanently fresh."""

        def explode() -> QuoteStore | None:
            raise RuntimeError("sheet unreachable")

        store = CachedQuoteStore(explode, ttl_seconds=300, initial=self._card(350.0))
        store._read_at -= 900
        store._refresh()

        assert store.cache_age_seconds >= 900

    def test_a_fixture_reports_no_age(self) -> None:
        """It is its own source; there is no sheet behind it to drift from."""
        assert self._card(350.0).cache_age_seconds == 0
