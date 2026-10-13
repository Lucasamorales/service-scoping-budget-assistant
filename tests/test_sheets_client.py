"""Reading tabs from the budget workbook when it lives in Google Sheets.

Every other test reads the checked-in xlsx fixture, so the Sheets path — the
one production takes — was not exercised at all. Here the Sheets API is
replaced by a stand-in with the client library's own call shape
(``spreadsheets().values().batchGet(...).execute()``), so the request that is
built and the handling of what comes back are the real code. Nothing leaves
the machine.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.store import sheets_client
from app.store.sheets_client import SheetsError, fetch_sheet_values, quote_sheet_title


class FakeSheets:
    """Answers ``batchGet`` with a canned response and records the request."""

    def __init__(self, response: dict[str, Any] | Exception) -> None:
        self._response = response
        self.requests: list[dict[str, Any]] = []

    def spreadsheets(self) -> FakeSheets:
        return self

    def values(self) -> FakeSheets:
        return self

    def batchGet(self, **kwargs: Any) -> FakeSheets:  # noqa: N802 - the API's name
        self.requests.append(kwargs)
        return self

    def execute(self) -> dict[str, Any]:
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


@pytest.fixture
def sheets(monkeypatch: pytest.MonkeyPatch):
    """Install a fake Sheets service and return a function that sets its reply."""
    holder: dict[str, Any] = {}

    def install(response: dict[str, Any] | Exception) -> FakeSheets:
        fake = FakeSheets(response)
        holder["fake"] = fake
        holder["credentials_path"] = None

        def service(*, credentials_path: str = "") -> FakeSheets:
            holder["credentials_path"] = credentials_path
            return fake

        monkeypatch.setattr(sheets_client, "sheets_service", service)
        return fake

    install.holder = holder  # type: ignore[attr-defined]
    return install


def ranges(*pairs: tuple[str, list[list[object]]]) -> dict[str, Any]:
    return {
        "valueRanges": [
            {"range": f"'{title}'!A1:Z99", "values": values} for title, values in pairs
        ]
    }


def test_each_requested_tab_comes_back_under_its_own_title(sheets) -> None:
    sheets(ranges(("Budget caps", [["Branch", "Jan"]]), ("DB", [["Timestamp"]])))
    out = fetch_sheet_values("sheet-1", ["Budget caps", "DB"])
    assert out == {"Budget caps": [["Branch", "Jan"]], "DB": [["Timestamp"]]}


def test_the_request_asks_for_raw_values_by_row(sheets) -> None:
    """Unformatted values and serial dates, so parsing matches the xlsx path."""
    fake = sheets(ranges(("Budget caps", []), ("Fiscal_calendar", [])))
    fetch_sheet_values("  sheet-1  ", ["Budget caps", "Fiscal_calendar"])
    assert fake.requests == [
        {
            "spreadsheetId": "sheet-1",
            "ranges": ["'Budget caps'", "'Fiscal_calendar'"],
            "majorDimension": "ROWS",
            "valueRenderOption": "UNFORMATTED_VALUE",
            "dateTimeRenderOption": "SERIAL_NUMBER",
        }
    ]


def test_empty_cells_become_none_and_real_values_are_kept(sheets) -> None:
    sheets(ranges(("DB", [["Acme London", "", 0, None, False, 51.68]])))
    rows = fetch_sheet_values("sheet-1", ["DB"])["DB"]
    assert rows == [["Acme London", None, 0, None, False, 51.68]]


def test_a_tab_with_no_values_is_an_empty_list(sheets) -> None:
    sheets({"valueRanges": [{"range": "'Roster'!A1:Z99"}]})
    assert fetch_sheet_values("sheet-1", ["Roster"]) == {"Roster": []}


def test_blank_titles_are_dropped_before_the_request(sheets) -> None:
    fake = sheets(ranges(("DB", [])))
    fetch_sheet_values("sheet-1", ["", "  ", " DB "])
    assert fake.requests[0]["ranges"] == ["'DB'"]


def test_no_titles_means_no_request_at_all(sheets) -> None:
    sheets(ranges())
    assert fetch_sheet_values("sheet-1", ["", " "]) == {}
    assert sheets.holder["fake"].requests == []


def test_an_empty_spreadsheet_id_is_refused(sheets) -> None:
    sheets(ranges())
    with pytest.raises(SheetsError, match="spreadsheet id is empty"):
        fetch_sheet_values("   ", ["DB"])
    assert sheets.holder["fake"].requests == []


def test_fewer_ranges_than_requested_is_refused_rather_than_paired_by_position(
    sheets,
) -> None:
    """Pairing by position would read one tab's rows with another tab's parser."""
    sheets(ranges(("Budget caps", [["Branch"]])))
    with pytest.raises(SheetsError, match=r"expected 2 ranges .* got 1"):
        fetch_sheet_values("sheet-1", ["Budget caps", "DB"])


def test_a_missing_value_ranges_field_is_the_same_refusal(sheets) -> None:
    sheets({})
    with pytest.raises(SheetsError, match=r"expected 1 ranges .* got 0"):
        fetch_sheet_values("sheet-1", ["DB"])


def test_an_api_failure_becomes_a_sheets_error_that_keeps_the_cause(sheets) -> None:
    boom = RuntimeError("HttpError 403: The caller does not have permission")
    sheets(boom)
    with pytest.raises(SheetsError, match="does not have permission") as raised:
        fetch_sheet_values("sheet-1", ["DB"])
    assert raised.value.__cause__ is boom


def test_a_sheets_error_from_building_the_client_is_passed_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def service(*, credentials_path: str = "") -> Any:
        raise SheetsError("google-api-python-client / google-auth not installed")

    monkeypatch.setattr(sheets_client, "sheets_service", service)
    with pytest.raises(SheetsError, match="not installed"):
        fetch_sheet_values("sheet-1", ["DB"])


def test_a_title_the_api_echoes_differently_is_also_available_under_that_name(
    sheets,
) -> None:
    """Whitespace drift between the configured title and the real tab."""
    sheets(
        {"valueRanges": [{"range": "'Budget caps '!A1:B2", "values": [["Branch", 1]]}]}
    )
    out = fetch_sheet_values("sheet-1", ["Budget caps"])
    assert out["Budget caps"] == [["Branch", 1]]
    assert out["Budget caps "] == [["Branch", 1]]


def test_the_credentials_path_is_handed_to_the_client_builder(sheets) -> None:
    sheets(ranges(("DB", [])))
    fetch_sheet_values("sheet-1", ["DB"], credentials_path="key.json")
    assert sheets.holder["credentials_path"] == "key.json"


@pytest.mark.parametrize(
    ("title", "quoted"),
    [
        ("DB", "'DB'"),
        ("Budget caps", "'Budget caps'"),
        ("Q1/Q2", "'Q1/Q2'"),
        ("Robin's tab", "'Robin''s tab'"),
    ],
)
def test_tab_titles_are_quoted_for_a1_notation(title: str, quoted: str) -> None:
    assert quote_sheet_title(title) == quoted
