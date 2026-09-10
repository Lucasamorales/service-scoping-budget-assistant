"""How a figure about money is written, everywhere it is written.

One function, because there used to be three answers. The rate card said
``£350``, the budget tools said ``500`` with no currency at all, and the model's
briefing said ``350.00`` — and two different helpers named ``_money`` sat in
different modules doing different things, which is a trap for whoever edits the
wrong one.

The format follows the wording stakeholders approved for a quote: a symbol, no
trailing zeros. ``£350`` rather than ``350.00 GBP``, because trailing zeros make
a ballpark look like an invoice and the sentence around it says "usually priced
at".

**One currency, deliberately.** The spreadsheet has no currency column — caps
are bare numbers on the ``Budget caps`` tab and the ``Branches/countries`` tab
names only countries — and the rate card carries a single ``currency`` field.
So the business tracks thirteen branches across four countries in one currency,
and this module assumes that too. If sites are ever denominated separately,
the fix is a currency per branch from the sheet, not a second format here.
"""

from __future__ import annotations

__all__ = ["DEFAULT_CURRENCY", "format_money"]

DEFAULT_CURRENCY = "GBP"
"""What a figure is denominated in when the caller has nothing better.

The budget tools are the caller in question: a :class:`BudgetSnapshot` comes
from a sheet that never says. The rate card does carry a currency and passes
it, so the two agree only because the business uses one — see the module note.
"""

_SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€", "CAD": "CA$", "AUD": "A$"}


def format_money(value: float | None, currency: str = DEFAULT_CURRENCY) -> str:
    """Write a figure the way the approved copy writes it: ``£350``.

    ``None`` becomes ``unknown`` rather than a zero. A missing cap and a cap of
    nothing are different facts, and printing ``£0`` for the first would state
    the second.

    Whole amounts lose their pence; anything else keeps them, so a real
    ``£350.50`` is never rounded into a figure nobody will be charged.

    An unrecognised currency falls back to its code — worse to read, impossible
    to misread. The wrong symbol on a number is a lie about money, and there is
    no version of this where guessing is better than being plain.
    """
    if value is None:
        return "unknown"
    code = currency.strip().upper() or DEFAULT_CURRENCY
    figure = f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    symbol = _SYMBOLS.get(code)
    return f"{symbol}{figure}" if symbol else f"{figure} {code}"
