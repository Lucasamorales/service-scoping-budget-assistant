"""Read-only Google Sheets client (Viewer share + service account).

Uses Application Default Credentials. Locally that is usually
``GOOGLE_APPLICATION_CREDENTIALS`` pointing at a service-account JSON key.
On Cloud Run it is the runtime service account. Never requests write scopes.

Live workbook tab titles (source of truth) — local xlsx fixtures may differ:
``Branches/countries``, ``DB``, ``Budget caps``, ``Fiscal_calendar``,
``Roster``, ``Pricing_tiers``, plus unused ``Dashboard`` / ``Scope``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import structlog

__all__ = [
    "TAB_CAPS",
    "TAB_DB",
    "TAB_FISCAL",
    "TAB_PRICING",
    "TAB_ROSTER",
    "TAB_SCOPE",
    "TAB_BRANCHES",
    "SheetsError",
    "fetch_sheet_values",
    "quote_sheet_title",
    "sheets_service",
]

logger = structlog.get_logger(__name__)

# Spreadsheet body read only — no drive.file write scopes.
_READONLY_SCOPES = ("https://www.googleapis.com/auth/spreadsheets.readonly",)

# Exact tab titles on the live acme_scope_db Google Sheet.
TAB_BRANCHES = "Branches/countries"
TAB_CAPS = "Budget caps"
TAB_FISCAL = "Fiscal_calendar"
TAB_DB = "DB"
TAB_ROSTER = "Roster"
TAB_PRICING = "Pricing_tiers"
TAB_SCOPE = "Scope"
"""Section / item / status / Tier. The business's own view of the
catalogue, and the only place the service-to-tier mapping is written
down. The verdicts on it are *not* read: those come from documents/,
which carry the reasoning a reply needs as well as the code."""


class SheetsError(RuntimeError):
    """Sheets API unavailable or the spreadsheet could not be read."""


def quote_sheet_title(title: str) -> str:
    """A1 notation for a tab name (required when the title has ``/`` or spaces)."""
    escaped = title.replace("'", "''")
    return f"'{escaped}'"


def sheets_service(*, credentials_path: str = "") -> Any:
    """Build a Sheets API v4 client from ADC or an explicit key file."""
    try:
        import google.auth
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise SheetsError(
            "google-api-python-client / google-auth not installed; "
            "pip install -e '.[cloud]'"
        ) from exc

    creds: Any
    if credentials_path.strip():
        creds = service_account.Credentials.from_service_account_file(
            credentials_path.strip(),
            scopes=_READONLY_SCOPES,
        )
    else:
        creds, _project = google.auth.default(scopes=list(_READONLY_SCOPES))
        if hasattr(creds, "refresh"):
            # A failure here is not fatal — the client refreshes lazily on the
            # first call — but swallowing it silently meant a bad credential
            # surfaced later as an unexplained "budget isn't loaded", with
            # nothing in the logs pointing at auth.
            try:
                creds.refresh(Request())
            except Exception as exc:  # noqa: BLE001 - google.auth raises many types
                logger.warning(
                    "sheets.credential_refresh_failed",
                    error=str(exc),
                    detail="continuing; the client will retry on first use",
                )

    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def fetch_sheet_values(
    spreadsheet_id: str,
    tab_titles: Sequence[str],
    *,
    credentials_path: str = "",
) -> dict[str, list[list[object]]]:
    """Return ``{tab_title: rows}`` for each requested tab (exact title keys).

    Empty cells become ``None`` so parsers match the xlsx path.
    """
    if not spreadsheet_id.strip():
        raise SheetsError("spreadsheet id is empty")
    titles = [t.strip() for t in tab_titles if t and t.strip()]
    if not titles:
        return {}

    ranges = [quote_sheet_title(title) for title in titles]

    try:
        service = sheets_service(credentials_path=credentials_path)
        response = (
            service.spreadsheets()
            .values()
            .batchGet(
                spreadsheetId=spreadsheet_id.strip(),
                ranges=ranges,
                majorDimension="ROWS",
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="SERIAL_NUMBER",
            )
            .execute()
        )
    except SheetsError:
        raise
    except Exception as exc:
        logger.error("sheets.fetch_failed", error=str(exc), spreadsheet=spreadsheet_id)
        raise SheetsError(str(exc)) from exc

    value_ranges = response.get("valueRanges") or []
    # batchGet returns one range per requested range, in order. If it ever does
    # not, pairing by position silently maps one tab's rows onto another tab's
    # parser — caps read as spend, spend read as roster. Refuse instead.
    if len(value_ranges) != len(titles):
        logger.error(
            "sheets.range_count_mismatch",
            spreadsheet=spreadsheet_id,
            requested=len(titles),
            returned=len(value_ranges),
        )
        raise SheetsError(
            f"expected {len(titles)} ranges from the Sheets API, got {len(value_ranges)}"
        )

    out: dict[str, list[list[object]]] = {}
    for title, entry in zip(titles, value_ranges, strict=True):
        rows_raw = entry.get("values") or []
        rows: list[list[object]] = []
        for row in rows_raw:
            rows.append([_cell(c) for c in row])
        out[title] = rows

    # Also key by whatever title the API echoed, in case of whitespace drift.
    for entry in value_ranges:
        key = str(entry.get("range") or "")
        echoed = key.split("!")[0].strip().strip("'") if key else ""
        if echoed and echoed not in out:
            rows_raw = entry.get("values") or []
            out[echoed] = [[_cell(c) for c in row] for row in rows_raw]

    logger.info(
        "sheets.fetched",
        spreadsheet=spreadsheet_id,
        tabs=sorted(out),
    )
    return out


def _cell(value: object) -> object | None:
    if value is None or value == "":
        return None
    return value
