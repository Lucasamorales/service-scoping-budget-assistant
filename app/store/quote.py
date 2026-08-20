"""Tier → price rate card (read-only fixture or future Sheet tabs).

Only tiers ``1``, ``2``, ``3``, and ``Variable`` are valid. Anything else is
rejected at load so a stale Tier 4 mapping cannot quote silently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import structlog

__all__ = ["ALLOWED_TIERS", "QuoteStore", "TierPrice", "load_quote_store"]

logger = structlog.get_logger(__name__)

TierPrice = float | Literal["Variable"]

ALLOWED_TIERS = frozenset({"1", "2", "3", "Variable"})


@dataclass(frozen=True, slots=True)
class QuoteStore:
    currency: str
    tiers: dict[str, TierPrice]
    services: dict[str, str]

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
) -> QuoteStore | None:
    """Load the rate card.

    With a spreadsheet id, ``Pricing tier`` on the live sheet is the source of
    truth for tier prices. The JSON file still supplies the service→tier map
    (until that also lives on the sheet). Without a spreadsheet id, JSON is
    used entirely for offline/dev.
    """
    store = _load_quote_json(path)
    if not spreadsheet_id.strip():
        return store

    try:
        sheet_tiers = _load_pricing_tiers_from_sheets(
            spreadsheet_id.strip(),
            credentials_path=credentials_path,
        )
    except Exception as exc:
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

    services = store.services if store is not None else {}
    currency = store.currency if store is not None else "GBP"
    # Sheet prices win; keep Variable from JSON if the tab only lists 1/2/3.
    tiers: dict[str, TierPrice] = dict(sheet_tiers)
    if "Variable" not in tiers:
        tiers["Variable"] = "Variable"
    logger.info("quote.sheets_tiers_loaded", tiers=sorted(str(k) for k in tiers))
    return QuoteStore(currency=currency, tiers=tiers, services=services)


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
    for service_key, tier in (raw.get("services") or {}).items():
        label = str(tier)
        if label not in ALLOWED_TIERS:
            logger.warning(
                "quote.ignored_service_tier",
                service=str(service_key),
                tier=label,
                path=str(path),
            )
            continue
        if label not in tiers:
            logger.warning(
                "quote.service_tier_missing_price",
                service=str(service_key),
                tier=label,
                path=str(path),
            )
            continue
        services[str(service_key)] = label

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
