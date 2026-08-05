"""Domain types for the service catalog.

The scope verdict a user receives is a field parsed out of the corpus, never
something a language model infers. These types are the shape that field takes
once it reaches the rest of the application.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from app.core.errors import UnknownStatusCodeError

__all__ = ["AtAGlance", "Chunk", "DocType", "ServiceItem", "Status"]


class DocType(StrEnum):
    """What kind of document this is, and therefore how it is handled.

    Author-declared in ``documents/manifest.json``. No heuristic reliably tells
    a service definition from a glossary from a set of pricing rules, and this
    choice drives both the chunking strategy and what retrieval is allowed to
    return for a given job.
    """

    SERVICE_ITEM = "service_item"
    """One row of the service breakdown, carrying an authoritative status."""

    GLOSSARY = "glossary"
    """Branch and country reference data."""

    DIRECTORY = "directory"
    """Who is responsible for what, per branch and per country."""

    BUSINESS_LOGIC = "business_logic"
    """Verdict modifiers, thresholds and routing rules."""

    META = "meta"
    """Source for the always-on prompt. Excluded from retrieval so the
    assistant never cites its own instructions back as evidence."""

    @property
    def excluded_from_retrieval(self) -> bool:
        return self is DocType.META


class Status(StrEnum):
    """The four verdicts the Acme service breakdown defines.

    The corpus writes these as ``Y``, ``N``, ``Local`` and ``On demand``. Those
    raw codes stay at the edge; everything inland uses these names.
    """

    IN_SCOPE = "in_scope"
    """Included in the retainer. No quote, no extra cost."""

    OUT_OF_SCOPE = "out_of_scope"
    """Cannot be included; it would require additional resources."""

    LOCAL = "local"
    """Delivered by the local site and operations teams, not central marketing."""

    QUOTE_REQUIRED = "quote_required"
    """Central marketing can deliver it, but it has to be quoted first."""

    @property
    def requires_quote(self) -> bool:
        """Whether reaching an answer needs the quoting engine and a budget check."""
        return self is Status.QUOTE_REQUIRED

    @classmethod
    def from_raw_code(cls, raw_code: str, *, source: str) -> Status:
        """Map a raw ``Status code`` field onto a verdict.

        Case and surrounding whitespace are treated as formatting and folded
        away, because the corpus is inconsistent about both. Anything else
        raises: a status this function does not recognise is a corpus bug, and
        guessing a default is how a paid service comes to be described as free.
        """
        normalized = " ".join(raw_code.split()).casefold()
        try:
            return _RAW_STATUS_CODES[normalized]
        except KeyError:
            raise UnknownStatusCodeError(raw_code, source) from None


_RAW_STATUS_CODES: Mapping[str, Status] = {
    "y": Status.IN_SCOPE,
    "n": Status.OUT_OF_SCOPE,
    "local": Status.LOCAL,
    "on demand": Status.QUOTE_REQUIRED,
}


@dataclass(frozen=True, slots=True)
class AtAGlance:
    """The four bullets every document carries under ``## At a Glance``.

    Every field is optional. A missing bullet is reported by the validator and
    left as ``None`` here rather than being invented.
    """

    in_scope: str | None = None
    delivered_by: str | None = None
    extra_cost_or_quote: str | None = None
    how_to_get_it: str | None = None


@dataclass(frozen=True, slots=True)
class ServiceItem:
    """One row of the Acme service breakdown, parsed from one document."""

    item_id: str
    """Canonical key from :func:`app.core.keys.service_key`."""

    section: str
    item: str
    status: Status
    status_raw: str
    """The status exactly as written in the document, kept so the validator can
    report which files need tidying without re-reading them."""

    status_meaning: str
    """The domain's own wording for the verdict. Presented to users in
    preference to anything phrased in code, so the corpus stays the single
    source of truth for how a verdict is described."""

    aliases: tuple[str, ...]
    at_a_glance: AtAGlance
    summary: str
    sections: Mapping[str, str]
    """Body text keyed by ``##`` heading, for chunking and targeted lookup."""

    body: str
    source: str
    """Filename the item was parsed from."""

    @property
    def display_name(self) -> str:
        """How the item is named back to a user."""
        return f"{self.item} ({self.section})"

    @property
    def search_terms(self) -> tuple[str, ...]:
        """Every phrase that should resolve to this item.

        The ``Also known as`` line is a retrieval hint written by a human who
        knows the domain. It costs nothing to match against and outperforms
        embeddings on the short, blunt phrasing real requests use.
        """
        return (self.item, *self.aliases)


@dataclass(frozen=True, slots=True)
class Chunk:
    """A unit of retrievable text.

    ``content`` is self-describing: it opens with a header naming the section,
    the item and the verdict, so a retrieved chunk carries its own provenance
    into the prompt and the model can cite it without a separate instruction
    explaining what it is reading.
    """

    chunk_id: str
    """``{source}:{chunk_index}``. Stable, and the deduplication key."""

    content: str
    source: str
    doc_type: DocType
    chunk_index: int
    """Order within the source document. Load bearing for neighbour-window
    expansion and for reconstructing a whole document from its parts."""

    item_id: str | None = None
    """Links a service item chunk back to its authoritative catalog entry."""

    section_title: str | None = None
    section: str | None = None
    """The catalog section, scored as its own weaker tier so that asking about
    "photography for a magazine" credits every Photography item without a
    section match ever outranking a match on the item itself."""
    use_when: tuple[str, ...] = ()
    """Human-written retrieval hints, from the ``Also known as`` line. These
    participate in keyword scoring, which is the cheapest relevance boost
    available and needs no embedding."""

    embedding: tuple[float, ...] | None = None
