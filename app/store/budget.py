"""Budget ledger and caps — local workbook now, Google Sheets later.

The Dashboard tab is ignored. Remaining budget is always recomputed from
``Budget caps`` minus summed ``DB`` spend for the fiscal month.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

import structlog

from app.core.keys import normalize_term, branch_key

__all__ = [
    "MONTHS",
    "BudgetSnapshot",
    "BudgetStore",
    "FiscalMonth",
    "SheetsBudgetStore",
    "SpendLine",
    "BranchRef",
    "XlsxBudgetStore",
    "build_budget_store",
    "canonical_month",
]

logger = structlog.get_logger(__name__)

MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

# Country / region rollup rows on the caps sheet — not branches.
_CAP_ROLLUPS = frozenset(
    normalize_term(name) for name in ("Australia", "Canada", "Paris", "United Kingdom", "France")
)


@dataclass(frozen=True, slots=True)
class BranchRef:
    """Canonical branch from the Branchescountries tab."""

    key: str
    name: str
    country: str
    location: str


@dataclass(frozen=True, slots=True)
class FiscalMonth:
    label: str
    """Short month label as on the sheet, e.g. ``Aug``."""

    start: date


@dataclass(frozen=True, slots=True)
class SpendLine:
    branch: str
    country: str
    media_type: str
    description: str
    po_number: str
    requester: str
    po_date: date | None
    amount: float
    month_label: str


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    branch: BranchRef
    month: str
    cap: float
    spent: float
    remaining: float
    lines: tuple[SpendLine, ...]

    @property
    def citation(self) -> str:
        return f"Budget tracker ({self.branch.name}, {self.month})"


class BudgetStore(Protocol):
    def branches(self) -> tuple[BranchRef, ...]: ...

    def resolve_branch(self, text: str) -> BranchRef | None: ...

    def fiscal_month_for(self, when: date) -> str: ...

    def snapshot(self, branch: BranchRef, month: str) -> BudgetSnapshot: ...


@dataclass(frozen=True, slots=True)
class _WorkbookData:
    branches: tuple[BranchRef, ...]
    by_key: dict[str, BranchRef]
    caps: dict[str, dict[str, float]]
    """branch key → month label → cap"""

    fiscal: tuple[FiscalMonth, ...]
    spend: tuple[SpendLine, ...]


class XlsxBudgetStore:
    """Read-only budget store backed by the exported workbook fixture."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data = _load_workbook(path)

    def branches(self) -> tuple[BranchRef, ...]:
        return self._data.branches

    def resolve_branch(self, text: str) -> BranchRef | None:
        return _resolve_branch(self._data, text)

    def fiscal_month_for(self, when: date) -> str:
        return _fiscal_month_for(self._data, when)

    def snapshot(self, branch: BranchRef, month: str) -> BudgetSnapshot:
        return _snapshot(self._data, branch, month, self.fiscal_month_for)


class SheetsBudgetStore:
    """Read-only budget store backed by a Google Sheet (Viewer access)."""

    def __init__(self, spreadsheet_id: str, *, credentials_path: str = "") -> None:
        self._spreadsheet_id = spreadsheet_id
        self._data = _load_sheets(spreadsheet_id, credentials_path=credentials_path)

    def branches(self) -> tuple[BranchRef, ...]:
        return self._data.branches

    def resolve_branch(self, text: str) -> BranchRef | None:
        return _resolve_branch(self._data, text)

    def fiscal_month_for(self, when: date) -> str:
        return _fiscal_month_for(self._data, when)

    def snapshot(self, branch: BranchRef, month: str) -> BudgetSnapshot:
        return _snapshot(self._data, branch, month, self.fiscal_month_for)


def _resolve_branch(data: _WorkbookData, text: str) -> BranchRef | None:
    key = branch_key(text)
    if key in data.by_key:
        return data.by_key[key]
    needle = normalize_term(text)
    for branch in data.branches:
        if needle == normalize_term(branch.name):
            return branch
        if needle == normalize_term(branch.location):
            return branch
    return None


def _fiscal_month_for(data: _WorkbookData, when: date) -> str:
    chosen = data.fiscal[0].label if data.fiscal else "Jan"
    for entry in data.fiscal:
        if entry.start <= when:
            chosen = entry.label
        else:
            break
    return chosen


def _snapshot(
    data: _WorkbookData,
    branch: BranchRef,
    month: str,
    fiscal_month_for,
) -> BudgetSnapshot:
    month = canonical_month(month)
    cap = data.caps.get(branch.key, {}).get(month, 0.0)
    lines = tuple(
        line
        for line in data.spend
        if branch_key(line.branch) == branch.key
        and _line_month(line, fiscal_month_for) == month
    )
    spent = round(sum(line.amount for line in lines), 2)
    remaining = round(cap - spent, 2)
    return BudgetSnapshot(
        branch=branch,
        month=month,
        cap=cap,
        spent=spent,
        remaining=remaining,
        lines=lines,
    )


def _line_month(line: SpendLine, fiscal_month_for) -> str:
    if line.po_date is not None:
        return fiscal_month_for(line.po_date)
    return canonical_month(line.month_label) if line.month_label else ""


def build_budget_store(
    *,
    xlsx_path: Path | None = None,
    spreadsheet_id: str = "",
    credentials_path: str = "",
) -> BudgetStore | None:
    """Load budget data.

    When ``spreadsheet_id`` is set the live Google Sheet is the **source of
    truth** — no silent fallback to the local xlsx. The xlsx path is only used
    for offline/dev when no spreadsheet id is configured.
    """
    if spreadsheet_id.strip():
        try:
            store = SheetsBudgetStore(
                spreadsheet_id.strip(),
                credentials_path=credentials_path,
            )
        except Exception as exc:
            logger.error(
                "budget.sheets_load_failed",
                spreadsheet=spreadsheet_id,
                error=str(exc),
                detail="spreadsheet is source of truth; not falling back to xlsx",
            )
            return None
        logger.info(
            "budget.sheets_loaded",
            spreadsheet=spreadsheet_id,
            branches=len(store.branches()),
        )
        return store

    path = xlsx_path or Path("fixtures/budget/acme_scope_db.xlsx")
    if not path.is_file():
        logger.warning("budget.xlsx_missing", path=str(path))
        return None
    try:
        store = XlsxBudgetStore(path)
    except Exception as exc:
        logger.error("budget.xlsx_load_failed", path=str(path), error=str(exc))
        return None
    logger.info("budget.xlsx_loaded", path=str(path), branches=len(store.branches()))
    return store


def canonical_month(label: str) -> str:
    """Normalise a month token to the three-letter labels used on the sheet."""
    raw = (label or "").strip()
    if not raw:
        return ""
    title = raw[:3].title()
    for month in MONTHS:
        if month == title or month.lower() == raw.lower()[:3]:
            return month
    full = {
        "january": "Jan",
        "february": "Feb",
        "march": "Mar",
        "april": "Apr",
        "may": "May",
        "june": "Jun",
        "july": "Jul",
        "august": "Aug",
        "september": "Sep",
        "october": "Oct",
        "november": "Nov",
        "december": "Dec",
    }
    return full.get(raw.lower(), title)


def _load_workbook(path: Path) -> _WorkbookData:
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        return _workbook_from_tabs(
            branches_rows=_sheet_rows(wb["Branchescountries"]),
            caps_rows=_sheet_rows(wb["Budget caps"]),
            fiscal_rows=_sheet_rows(wb["Fiscal_calendar"]),
            spend_rows=_sheet_rows(wb["DB"]),
        )
    finally:
        wb.close()


def _load_sheets(spreadsheet_id: str, *, credentials_path: str = "") -> _WorkbookData:
    from app.store.sheets_client import (
        TAB_CAPS,
        TAB_DB,
        TAB_FISCAL,
        TAB_BRANCHES,
        SheetsError,
        fetch_sheet_values,
    )

    try:
        tabs = fetch_sheet_values(
            spreadsheet_id,
            (TAB_BRANCHES, TAB_CAPS, TAB_FISCAL, TAB_DB),
            credentials_path=credentials_path,
        )
    except SheetsError:
        raise
    return _workbook_from_tabs(
        branches_rows=tabs.get(TAB_BRANCHES) or [],
        caps_rows=tabs.get(TAB_CAPS) or [],
        fiscal_rows=tabs.get(TAB_FISCAL) or [],
        spend_rows=tabs.get(TAB_DB) or [],
    )


def _sheet_rows(ws: object) -> list[list[object]]:
    return [list(row) for row in ws.iter_rows(values_only=True)]  # type: ignore[attr-defined]


def _workbook_from_tabs(
    *,
    branches_rows: list[list[object]],
    caps_rows: list[list[object]],
    fiscal_rows: list[list[object]],
    spend_rows: list[list[object]],
) -> _WorkbookData:
    branches = _read_branches(branches_rows)
    by_key = {branch.key: branch for branch in branches}
    caps = _read_caps(caps_rows, by_key)
    fiscal = _read_fiscal(fiscal_rows)
    spend = _read_spend(spend_rows)
    branches = tuple(by_key[key] for key in sorted(by_key))
    return _WorkbookData(
        branches=branches,
        by_key=by_key,
        caps=caps,
        fiscal=fiscal,
        spend=spend,
    )


def _read_branches(rows: list[list[object]]) -> tuple[BranchRef, ...]:
    out: list[BranchRef] = []
    for i, row in enumerate(rows):
        if i == 0 or not row or row[0] is None:
            continue
        country = str(row[0]).strip()
        location = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
        name = (
            str(row[2]).strip()
            if len(row) > 2 and row[2] is not None
            else f"Acme {location}"
        )
        if not name:
            continue
        out.append(
            BranchRef(
                key=branch_key(name),
                name=name,
                country=country,
                location=location,
            )
        )
    return tuple(out)


def _read_caps(
    rows: list[list[object]], by_key: dict[str, BranchRef]
) -> dict[str, dict[str, float]]:
    if not rows:
        return {}
    headers = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
    month_indexes = {month: headers.index(month) for month in MONTHS if month in headers}
    caps: dict[str, dict[str, float]] = {}
    for row in rows[1:]:
        if not row or row[0] is None:
            continue
        name = str(row[0]).strip()
        if normalize_term(name) in _CAP_ROLLUPS:
            continue
        key = branch_key(name)
        if key not in by_key:
            by_key[key] = BranchRef(key=key, name=name, country="", location=name)
        month_caps: dict[str, float] = {}
        for month, idx in month_indexes.items():
            if idx < len(row) and row[idx] is not None:
                try:
                    month_caps[month] = float(row[idx])  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    continue
        caps[key] = month_caps
    return caps


def _read_fiscal(rows: list[list[object]]) -> tuple[FiscalMonth, ...]:
    out: list[FiscalMonth] = []
    for i, row in enumerate(rows):
        if i == 0 or not row or row[0] is None:
            continue
        start = _as_date(row[0])
        label = canonical_month(str(row[1])) if len(row) > 1 and row[1] is not None else ""
        if start is None or not label:
            continue
        out.append(FiscalMonth(label=label, start=start))
    out.sort(key=lambda entry: entry.start)
    return tuple(out)


def _read_spend(rows: list[list[object]]) -> tuple[SpendLine, ...]:
    out: list[SpendLine] = []
    for i, row in enumerate(rows):
        if i == 0 or not row:
            continue
        if len(row) < 9 or row[2] is None or row[8] is None:
            continue
        try:
            amount = float(row[8])  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        out.append(
            SpendLine(
                branch=str(row[2]).strip(),
                country=str(row[1]).strip() if row[1] is not None else "",
                media_type=str(row[3]).strip() if len(row) > 3 and row[3] is not None else "",
                description=str(row[4]).strip() if len(row) > 4 and row[4] is not None else "",
                po_number=str(row[5]).strip() if len(row) > 5 and row[5] is not None else "",
                requester=str(row[6]).strip() if len(row) > 6 and row[6] is not None else "",
                po_date=_as_date(row[7]) if len(row) > 7 else None,
                amount=amount,
                month_label=(
                    str(row[9]).strip() if len(row) > 9 and row[9] is not None else ""
                ),
            )
        )
    return tuple(out)


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    # Sheets SERIAL_NUMBER (days since 1899-12-30).
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            from datetime import timedelta

            return (datetime(1899, 12, 30) + timedelta(days=float(value))).date()
        except (OverflowError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        raw = value.strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(raw[:10], fmt).date()
            except ValueError:
                continue
    return None
