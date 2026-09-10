"""One way to write a figure about money, checked at the edges."""

from __future__ import annotations

import pytest

from app.core.money import format_money


class TestFormatMoney:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (350.0, "£350"),
            (100.0, "£100"),
            (2500.0, "£2,500"),
            (0.0, "£0"),
        ],
    )
    def test_whole_amounts_lose_their_pence(self, value: float, expected: str) -> None:
        """£350, not £350.00. Trailing zeros make a ballpark read as an invoice,
        and the approved copy says "usually priced at"."""
        assert format_money(value) == expected

    def test_pence_survive_when_they_are_real(self) -> None:
        """Rounding would name a figure nobody will be charged."""
        assert format_money(350.5) == "£350.50"

    def test_missing_is_unknown_not_zero(self) -> None:
        """A cap the sheet does not carry and a cap of nothing are different
        facts. Printing £0 for the first states the second."""
        assert format_money(None) == "unknown"

    def test_a_known_currency_gets_its_symbol(self) -> None:
        assert format_money(350.0, "USD") == "$350"

    def test_an_unknown_currency_falls_back_to_its_code(self) -> None:
        """Worse to read, impossible to misread. The wrong symbol on a number
        is a lie about money."""
        assert format_money(350.0, "ZZZ") == "350 ZZZ"

    def test_currency_is_matched_regardless_of_case_or_padding(self) -> None:
        assert format_money(350.0, " gbp ") == "£350"


class TestGuardStillSeesTheseFigures:
    """The reply guard compares figures between the facts and the prose.

    Changing how money is written must not change what counts as the same
    number, or a correct reply starts being rejected for quoting its own
    source.
    """

    def test_the_formatted_figure_normalises_to_the_raw_one(self) -> None:
        from app.orchestrator.facts import figures_in

        assert figures_in(format_money(350.0)) == figures_in("350.00")
        assert figures_in(format_money(2500.0)) == figures_in("2500")
