"""Error types raised while loading and validating the knowledge corpus."""

from __future__ import annotations


class AcmeError(Exception):
    """Base class for every error this application raises deliberately."""


class CatalogError(AcmeError):
    """The service catalog could not be built from the corpus."""


class UnknownStatusCodeError(CatalogError):
    """A document declared a status code outside the four the domain defines.

    Deliberately fatal. Defaulting an unrecognised code would let a paid
    service silently present itself as free of charge.
    """

    def __init__(self, raw_code: str, source: str) -> None:
        self.raw_code = raw_code
        self.source = source
        super().__init__(f"{source}: unrecognised status code {raw_code!r}")


class MalformedDocumentError(CatalogError):
    """A document is missing a field the parser needs to identify the item."""

    def __init__(self, source: str, detail: str) -> None:
        self.source = source
        super().__init__(f"{source}: {detail}")
