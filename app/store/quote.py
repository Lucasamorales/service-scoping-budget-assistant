"""What an on-demand service costs: which tier it is, and what that tier is worth.

Both halves come from the live spreadsheet when one is configured. ``Scope``
carries the service-to-tier mapping in its ``Tier`` column, and
``Pricing_tiers`` carries tier-to-price. The JSON fixture is the offline
fallback and nothing more.

That split matters, because the fixture used to own the mapping and drifted
from the sheet without anything noticing. Merch was written down as Tier 1
where the sheet says Tier 3, so the assistant quoted £100 for a £350 service —
with a note in the file admitting the value had been guessed "pending sheet
confirmation". Fifteen other on-demand services were absent from the fixture
altogether and could not be priced at all, while the sheet had a tier for every
one of them.

Only tiers ``1``, ``2``, ``3``, and ``Variable`` are valid. Anything else is
rejected at load so a stale Tier 4 mapping cannot quote silently.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import structlog

from app.core.keys import service_key

__all__ = [
    "ALLOWED_TIERS",
    "CachedQuoteStore",
    "QuoteStore",
    "RateCard",
    "TierPrice",
    "load_quote_store",
]

logger = structlog.get_logger(__name__)

TierPrice = float | Literal["Variable"]

ALLOWED_TIERS = frozenset({"1", "2", "3", "Variable"})


class RateCard(Protocol):
    """What a caller needs from the rate card, however it is kept current."""

    @property
    def currency(self) -> str: ...

    @property
    def tiers(self) -> dict[str, TierPrice]: ...

    @property
    def services(self) -> dict[str, str]: ...

    @property
    def cache_age_seconds(self) -> int:
        """Seconds since these prices were read from their source."""
        ...

    def tier_for(self, service_key: str) -> str | None: ...

    def price_for_tier(self, tier: str) -> TierPrice | None: ...

    def lookup(self, service_key: str) -> tuple[str, TierPrice] | None: ...


@dataclass(frozen=True, slots=True)
class QuoteStore:
    currency: str
    tiers: dict[str, TierPrice]
    services: dict[str, str]

    @property
    def cache_age_seconds(self) -> int:
        """Always zero. A fixture read from disk is its own source of truth;
        there is no sheet behind it that could have moved on."""
        return 0

    def tier_for(self, service_key: str) -> str | None:
        return self.services.get(service_key)

    def price_for_tier(self, tier: str) -> TierPrice | None:
        if tier in self.tiers:
            return self.tiers[tier]
        return self.tiers.get(str(tier))

    def lookup(self, service_key: str) -> tuple[str, TierPrice] | None:
        tier = self.tier_for(service_key)
        if tier is None:
            return None
        price = self.price_for_tier(tier)
        if price is None:
            return None
        return tier, price


def load_quote_store(
    path: Path,
    *,
    spreadsheet_id: str = "",
    credentials_path: str = "",
    known_items: frozenset[str] | None = None,
    ttl_seconds: int = 0,
) -> RateCard | None:
    """Load the rate card.

    With a spreadsheet id the live sheet is the source of truth for both
    halves: ``Pricing_tiers`` for what a tier costs, ``Scope`` for which tier
    a service is. Without one, the JSON fixture supplies both for offline work.

    A sheet that cannot be read is never papered over with fixture numbers.
    Quoting a stale price as though it were live is the failure this whole
    module exists to avoid, so the store degrades to "I cannot price this"
    instead.

    ``known_items`` are the catalog ids the corpus can actually answer for.
    They change nothing about what loads; they only let a sheet row that names
    a service no document matches be reported at startup instead of going
    unnoticed.

    ``ttl_seconds`` re-reads the sheet in the background of a long-lived
    process. Zero keeps the old behaviour of reading once, which is right for
    the fixture and for one-shot scripts.
    """
    fixture = _load_quote_json(path)
    if not spreadsheet_id.strip():
        return fixture

    def loader() -> QuoteStore | None:
        return _load_from_sheets(
            fixture,
            spreadsheet_id.strip(),
            credentials_path=credentials_path,
            known_items=known_items,
        )

    initial = loader()
    if initial is None or ttl_seconds <= 0:
        return initial
    return CachedQuoteStore(loader, ttl_seconds=ttl_seconds, initial=initial)


def _load_from_sheets(
    store: QuoteStore | None,
    spreadsheet_id: str,
    *,
    credentials_path: str,
    known_items: frozenset[str] | None,
) -> QuoteStore | None:
    """One read of both tabs, assembled into a card. Safe to call repeatedly."""
    try:
        sheet_tiers = _load_pricing_tiers_from_sheets(
            spreadsheet_id,
            credentials_path=credentials_path,
        )
    except Exception as exc:  # noqa: BLE001 - never quote stale JSON prices as live
        logger.error(
            "quote.sheets_tiers_failed",
            error=str(exc),
            detail="spreadsheet is source of truth; not using JSON tier prices",
        )
        # Keep service→tier map from JSON if present, but clear numeric prices
        # so we cannot quote stale fixture numbers as if they were live.
        if store is None:
            return None
        return QuoteStore(
            currency=store.currency,
            tiers={"Variable": "Variable"},
            services=store.services,
        )

    if not sheet_tiers:
        logger.error(
            "quote.sheets_tiers_empty",
            detail="Pricing tier tab missing or empty; refusing JSON price fallback",
        )
        if store is None:
            return None
        return QuoteStore(
            currency=store.currency,
            tiers={"Variable": "Variable"},
            services=store.services,
        )

    currency = store.currency if store is not None else "GBP"

    # The mapping comes from the sheet too. Falling back to the fixture here
    # is what let the two drift: the file said Merch was Tier 1 while the
    # sheet said Tier 3, and nothing compared them.
    try:
        services = _load_service_tiers_from_sheets(
            spreadsheet_id,
            credentials_path=credentials_path,
            known_items=known_items,
        )
    except Exception as exc:  # noqa: BLE001 - any read failure falls back, loudly
        logger.error(
            "quote.sheets_scope_failed",
            error=str(exc),
            detail="falling back to the fixture service-to-tier map, which may be stale",
        )
        services = store.services if store is not None else {}
    else:
        if services:
            logger.info("quote.sheets_services_loaded", services=len(services))
        else:
            logger.error(
                "quote.sheets_scope_empty",
                detail="Scope tab had no on-demand rows with a tier; using the fixture",
            )
            services = store.services if store is not None else {}

    # Sheet prices win; keep Variable from JSON if the tab only lists 1/2/3.
    tiers: dict[str, TierPrice] = dict(sheet_tiers)
    if "Variable" not in tiers:
        tiers["Variable"] = "Variable"
    logger.info("quote.sheets_tiers_loaded", tiers=sorted(str(k) for k in tiers))
    return QuoteStore(currency=currency, tiers=tiers, services=services)


class CachedQuoteStore:
    """A rate card that re-reads the sheet, so prices do not need a restart.

    The static store is loaded once and frozen, which was fine while the tier
    map lived in a file that only changed with a deploy. Now that the business
    owns both halves on the sheet, a re-tiered service would have kept quoting
    the old price until the container happened to recycle — and with
    ``--min-instances 0`` that is minutes on a quiet day and hours on a busy
    one, which is no kind of guarantee.

    Two clocks, for the same reason as the budget cache: only a successful read
    moves ``_read_at``, so :attr:`cache_age_seconds` keeps growing while
    refreshes fail instead of resetting and hiding it.

    A failed refresh keeps the last good card. Prices that are five minutes old
    are worth far more than no price at all, and the staleness is reported
    rather than guessed at.
    """

    def __init__(
        self,
        loader: Callable[[], QuoteStore | None],
        *,
        ttl_seconds: int,
        initial: QuoteStore,
    ) -> None:
        self._loader = loader
        self._ttl = max(int(ttl_seconds), 0)
        self._lock = threading.Lock()
        self._data = initial
        now = time.monotonic()
        self._read_at = now
        self._tried_at = now

    @property
    def cache_age_seconds(self) -> int:
        return int(time.monotonic() - self._read_at)

    def _current(self) -> QuoteStore:
        if self._ttl and time.monotonic() - self._tried_at >= self._ttl:
            self._refresh()
        return self._data

    def _refresh(self) -> None:
        with self._lock:
            # Another thread may have refreshed while this one waited.
            if time.monotonic() - self._tried_at < self._ttl:
                return
            try:
                fresh = self._loader()
            except Exception as exc:  # noqa: BLE001 - keep the last good card
                logger.warning(
                    "quote.refresh_failed",
                    error=str(exc),
                    age_seconds=self.cache_age_seconds,
                    detail="serving the previously loaded rate card",
                )
            else:
                if fresh is None:
                    logger.warning(
                        "quote.refresh_empty",
                        age_seconds=self.cache_age_seconds,
                        detail="sheet read returned nothing; keeping the last card",
                    )
                else:
                    self._data = fresh
                    self._read_at = time.monotonic()
                    logger.info("quote.refreshed", services=len(fresh.services))
            # Stamped either way, so a persistent failure retries on the TTL
            # rather than on every single question.
            self._tried_at = time.monotonic()

    @property
    def currency(self) -> str:
        return self._current().currency

    @property
    def tiers(self) -> dict[str, TierPrice]:
        return self._current().tiers

    @property
    def services(self) -> dict[str, str]:
        return self._current().services

    def tier_for(self, service_key: str) -> str | None:
        return self._current().tier_for(service_key)

    def price_for_tier(self, tier: str) -> TierPrice | None:
        return self._current().price_for_tier(tier)

    def lookup(self, service_key: str) -> tuple[str, TierPrice] | None:
        return self._current().lookup(service_key)


def _load_quote_json(path: Path) -> QuoteStore | None:
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    tiers: dict[str, TierPrice] = {}
    for key, value in (raw.get("tiers") or {}).items():
        label = str(key)
        if label not in ALLOWED_TIERS:
            logger.warning("quote.ignored_tier", tier=label, path=str(path))
            continue
        if isinstance(value, str) and value.lower() == "variable":
            tiers[label] = "Variable"
        else:
            tiers[label] = float(value)

    services: dict[str, str] = {}
    for name, tier in (raw.get("services") or {}).items():
        label = str(tier)
        if label not in ALLOWED_TIERS:
            logger.warning(
                "quote.ignored_service_tier",
                service=str(name),
                tier=label,
                path=str(path),
            )
            continue
        if label not in tiers:
            logger.warning(
                "quote.service_tier_missing_price",
                service=str(name),
                tier=label,
                path=str(path),
            )
            continue
        services[str(name)] = label

    return QuoteStore(
        currency=str(raw.get("currency") or "GBP"),
        tiers=tiers,
        services=services,
    )


def _load_pricing_tiers_from_sheets(
    spreadsheet_id: str,
    *,
    credentials_path: str = "",
) -> dict[str, TierPrice]:
    from app.store.sheets_client import TAB_PRICING, fetch_sheet_values

    tabs = fetch_sheet_values(
        spreadsheet_id,
        (TAB_PRICING,),
        credentials_path=credentials_path,
    )
    rows = tabs.get(TAB_PRICING) or []
    return _parse_pricing_tier_rows(rows)


def _load_service_tiers_from_sheets(
    spreadsheet_id: str,
    *,
    credentials_path: str = "",
    known_items: frozenset[str] | None = None,
) -> dict[str, str]:
    from app.store.sheets_client import TAB_SCOPE, fetch_sheet_values

    tabs = fetch_sheet_values(
        spreadsheet_id,
        (TAB_SCOPE,),
        credentials_path=credentials_path,
    )
    return _parse_scope_rows(tabs.get(TAB_SCOPE) or [], known_items=known_items)


def _parse_scope_rows(
    rows: list[list[object]],
    *,
    known_items: frozenset[str] | None = None,
) -> dict[str, str]:
    """Read ``section | item | status | Tier`` into a service-to-tier map.

    Only ``On demand`` rows are read. A row saying Yes or Local has no price,
    and carrying a tier for one would invite quoting a service that is free.

    Keys are built with :func:`service_key`, the same function the corpus uses
    for its own ids, so a row lines up with a document by section and item
    name. When ``known_items`` is supplied, a row naming something the corpus
    does not have is logged rather than dropped in silence: the tier is real
    but unreachable, and the two views of the catalogue have drifted apart.
    Which side is wrong is a judgement for a person, so the row is still
    returned — an unreachable key is inert, a hidden one is a mystery.
    """
    out: dict[str, str] = {}
    unmatched: list[str] = []
    for index, row in enumerate(rows):
        cells = [str(cell).strip() if cell is not None else "" for cell in row]
        if len(cells) < 4 or not cells[0] or not cells[1]:
            continue
        if index == 0 and cells[2].lower() == "status":
            continue
        if cells[2].lower() != "on demand":
            continue
        label = _normalize_tier_label(cells[3])
        if label is None:
            logger.warning(
                "quote.scope_bad_tier",
                section=cells[0],
                item=cells[1],
                tier=cells[3],
                detail="tier is not 1, 2, 3 or Variable; this service cannot be priced",
            )
            continue
        key = service_key(cells[0], cells[1])
        out[key] = label
        if known_items is not None and key not in known_items:
            unmatched.append(f"{cells[0]} | {cells[1]}")

    if unmatched:
        logger.warning(
            "quote.scope_items_not_in_catalog",
            items=sorted(unmatched),
            detail="sheet rows with a tier that no corpus document answers to; "
            "the price is unreachable until one side is renamed",
        )
    logger.info("quote.scope_rows_read", priced=len(out), unmatched=len(unmatched))
    return out


def _parse_pricing_tier_rows(rows: list[list[object]]) -> dict[str, TierPrice]:
    """Accept ``Tier / Price`` rows like ``Tier 1`` / ``100`` or ``1`` / ``100``."""
    out: dict[str, TierPrice] = {}
    for i, row in enumerate(rows):
        if not row or row[0] is None:
            continue
        if i == 0 and "tier" in str(row[0]).lower():
            continue
        label = _normalize_tier_label(str(row[0]))
        if label is None or label not in ALLOWED_TIERS:
            continue
        if label == "Variable":
            out[label] = "Variable"
            continue
        if len(row) < 2 or row[1] is None:
            continue
        try:
            out[label] = float(row[1])  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return out


def _normalize_tier_label(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    lower = text.lower()
    if lower == "variable":
        return "Variable"
    # "Tier 1", "tier1", "1"
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits in {"1", "2", "3"}:
        return digits
    return None
