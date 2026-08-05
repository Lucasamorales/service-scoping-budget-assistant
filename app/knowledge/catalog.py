"""Parses the service breakdown corpus into an authoritative registry.

This module is the reason the assistant can be trusted. Every document carries
a ``Status code`` field stating whether the service is included, refused,
handled locally, or needs a quote. That is a fact, so it is read, not inferred.
Retrieval and the language model supply the wording around the verdict; they
never choose it.

Parsing is deliberately intolerant. An unrecognised status code raises rather
than defaulting, because the failure mode of a silent default is an Account
Manager being told a chargeable service is free.

Everything softer than that is collected as a :class:`CatalogIssue` rather than
raised, so one run reports every problem in the corpus instead of stopping at
the first.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from app.core.errors import CatalogError, MalformedDocumentError, UnknownStatusCodeError
from app.core.keys import normalize_term, service_key
from app.core.types import AtAGlance, ServiceItem, Status
from app.knowledge.manifest import DocType, Manifest

__all__ = [
    "CatalogIssue",
    "CatalogLoadResult",
    "ServiceCatalog",
    "Severity",
    "load_catalog",
    "parse_service_document",
]

_FIELD_RE = re.compile(r"^\*\*(?P<name>[^:*]+):\*\*[ \t]*(?P<value>.*)$", re.MULTILINE)
_BULLET_RE = re.compile(r"^-[ \t]+\*\*(?P<name>[^:*]+):\*\*[ \t]*(?P<value>.*)$", re.MULTILINE)
_SECTION_HEADING_RE = re.compile(r"^##[ \t]+(?P<title>.+?)[ \t]*$")
_TITLE_RE = re.compile(r"^#[ \t]+(?P<title>.+?)[ \t]*$", re.MULTILINE)
_ALIAS_SEPARATOR_RE = re.compile(r"[,;]")

# The heading naming the status embeds the status itself, so it differs from
# file to file. Matched by shape rather than by exact text.
_STATUS_SECTION_RE = re.compile(r"^what the .* status means for this item$")

_REQUIRED_SECTIONS = ("summary", "what this item covers", "at a glance", "likely questions")

_AT_A_GLANCE_FIELDS = {
    "in scope included": "in_scope",
    "delivered by": "delivered_by",
    "extra cost or quote required": "extra_cost_or_quote",
    "what to do to get it": "how_to_get_it",
}


class Severity(StrEnum):
    """How loudly an issue should be treated."""

    ERROR = "error"
    """Fails the build. The corpus cannot be trusted until it is fixed."""

    WARNING = "warning"
    """Reported for a human to read. Does not block."""


@dataclass(frozen=True, slots=True)
class CatalogIssue:
    severity: Severity
    source: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.upper():7}] {self.source}: {self.message}"


def _parse_fields(text: str) -> dict[str, str]:
    """Read the ``**Name:** value`` header block into a normalised mapping.

    Values are returned exactly as written, trailing spaces included, so the
    validator can report which documents need tidying. Callers strip.
    """
    return {
        normalize_term(match.group("name")): match.group("value")
        for match in _FIELD_RE.finditer(text)
    }


def _split_sections(text: str) -> dict[str, str]:
    """Split the body into ``##`` sections, keyed by their literal heading."""
    sections: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []

    for line in text.splitlines():
        heading = _SECTION_HEADING_RE.match(line)
        if heading:
            if current is not None:
                sections[current] = "\n".join(buffer).strip()
            current = heading.group("title")
            buffer = []
        elif current is not None:
            buffer.append(line)

    if current is not None:
        sections[current] = "\n".join(buffer).strip()
    return sections


def _parse_aliases(raw: str) -> tuple[str, ...]:
    """Split the ``Also known as`` line into individual phrases."""
    candidates = (part.strip() for part in _ALIAS_SEPARATOR_RE.split(raw))
    return tuple(candidate for candidate in candidates if candidate)


def _parse_at_a_glance(body: str) -> AtAGlance:
    """Read the four bullets, leaving any that are absent as ``None``."""
    found: dict[str, str] = {}
    for match in _BULLET_RE.finditer(body):
        key = _AT_A_GLANCE_FIELDS.get(normalize_term(match.group("name")))
        if key:
            found[key] = match.group("value").strip()
    return AtAGlance(**found)


def _document_title(text: str) -> str | None:
    match = _TITLE_RE.search(text)
    return match.group("title") if match else None


def _section_body(sections: Mapping[str, str], heading: str) -> str:
    """Look a section up by its normalised heading, tolerating how it is written."""
    for actual, body in sections.items():
        if normalize_term(actual) == heading:
            return body
    return ""


def _title_names_item(title: str, item: str) -> bool:
    """Whether an ``# H1`` line and the ``Item`` field describe the same thing.

    Compared after normalisation, so a difference in casing or punctuation is
    not reported. Only a genuinely different name is worth a human's attention.
    """
    # Both dash characters appear in real exports, so both have to be handled.
    for separator in (" \u2014 ", " \u2013 ", " - "):
        if separator in title:
            title = title.rsplit(separator, 1)[0]
            break
    return normalize_term(title) == normalize_term(item)


def parse_service_document(text: str, source: str) -> tuple[ServiceItem, list[CatalogIssue]]:
    """Parse one service breakdown document.

    Raises :class:`MalformedDocument` if the item cannot be identified and
    :class:`UnknownStatusCode` if its verdict cannot be trusted. Every other
    inconsistency is returned alongside the item as an issue.
    """
    issues: list[CatalogIssue] = []
    fields = _parse_fields(text)

    section = fields.get("section", "").strip()
    item = fields.get("item", "").strip()
    if not section or not item:
        missing = " and ".join(
            name for name, value in (("Section", section), ("Item", item)) if not value
        )
        raise MalformedDocumentError(source, f"missing {missing} field")

    # Kept unstripped so the formatting check below has something to see.
    status_raw = fields.get("status code", "")
    if not status_raw.strip():
        raise MalformedDocumentError(source, "missing Status code field")
    status = Status.from_raw_code(status_raw, source=source)

    if status_raw != status_raw.strip() or "  " in status_raw.strip():
        issues.append(
            CatalogIssue(
                Severity.WARNING,
                source,
                f"status code {status_raw!r} has stray whitespace; normalised to "
                f"{' '.join(status_raw.split())!r}",
            )
        )

    status_meaning = fields.get("status meaning", "").strip()
    if not status_meaning:
        issues.append(CatalogIssue(Severity.WARNING, source, "missing Status meaning field"))

    aliases = _parse_aliases(fields.get("also known as", ""))
    if not aliases:
        issues.append(
            CatalogIssue(
                Severity.WARNING,
                source,
                "no Also known as aliases; this item is reachable only by its exact name",
            )
        )

    sections = _split_sections(text)
    normalized_headings = {normalize_term(heading) for heading in sections}
    for required in _REQUIRED_SECTIONS:
        if required not in normalized_headings:
            issues.append(CatalogIssue(Severity.WARNING, source, f"missing '{required}' section"))
    if not any(_STATUS_SECTION_RE.match(heading) for heading in normalized_headings):
        issues.append(
            CatalogIssue(Severity.WARNING, source, "missing 'What the ... Status Means' section")
        )

    at_a_glance = _parse_at_a_glance(_section_body(sections, "at a glance"))
    for name in ("in_scope", "delivered_by", "extra_cost_or_quote", "how_to_get_it"):
        if getattr(at_a_glance, name) is None:
            issues.append(CatalogIssue(Severity.WARNING, source, f"At a Glance missing {name}"))

    title = _document_title(text)
    if title and not _title_names_item(title, item):
        issues.append(
            CatalogIssue(
                Severity.WARNING,
                source,
                f"title {title!r} does not name the Item field {item!r}",
            )
        )

    item_id = service_key(section, item)
    # Compared against the raw stem, not a re-slugified one: slugify collapses
    # runs of punctuation, which would eat the ``--`` separating section from
    # item and make every filename look wrong.
    if Path(source).stem.casefold() != item_id:
        issues.append(
            CatalogIssue(
                Severity.WARNING,
                source,
                f"filename does not match the item it contains; expected {item_id}.md",
            )
        )

    parsed = ServiceItem(
        item_id=item_id,
        section=section,
        item=item,
        status=status,
        status_raw=status_raw,
        status_meaning=status_meaning,
        aliases=aliases,
        at_a_glance=at_a_glance,
        summary=_section_body(sections, "summary"),
        sections=MappingProxyType(dict(sections)),
        body=text,
        source=source,
    )
    return parsed, issues


@dataclass(frozen=True, slots=True)
class ServiceCatalog:
    """The authoritative registry of every service Acme does or does not offer."""

    items: Mapping[str, ServiceItem]
    alias_index: Mapping[str, tuple[str, ...]]
    """Normalised phrase to the items it could mean.

    A phrase maps to several items more often than you would expect: this
    corpus has video editing under three different sections. Ambiguity is
    preserved here so the resolver can ask which one is meant, rather than a
    last-write-wins index quietly hiding two of the three.
    """

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self) -> Iterator[ServiceItem]:
        return iter(self.items.values())

    def get(self, item_id: str) -> ServiceItem | None:
        return self.items.get(item_id)

    def require(self, item_id: str) -> ServiceItem:
        found = self.items.get(item_id)
        if found is None:
            raise CatalogError(f"No catalog item {item_id!r}")
        return found

    def by_status(self, status: Status) -> tuple[ServiceItem, ...]:
        return tuple(item for item in self if item.status is status)

    def sections(self) -> tuple[str, ...]:
        return tuple(sorted({item.section for item in self}))

    def lookup_phrase(self, phrase: str) -> tuple[ServiceItem, ...]:
        """Return every item that declares the given phrase as a name or alias."""
        return tuple(
            self.items[item_id] for item_id in self.alias_index.get(normalize_term(phrase), ())
        )

    @classmethod
    def build(cls, items: Sequence[ServiceItem]) -> ServiceCatalog:
        alias_index: dict[str, list[str]] = {}
        for item in items:
            for term in item.search_terms:
                normalized = normalize_term(term)
                if not normalized:
                    continue
                bucket = alias_index.setdefault(normalized, [])
                if item.item_id not in bucket:
                    bucket.append(item.item_id)

        return cls(
            items=MappingProxyType({item.item_id: item for item in items}),
            alias_index=MappingProxyType(
                {term: tuple(ids) for term, ids in sorted(alias_index.items())}
            ),
        )


@dataclass(frozen=True, slots=True)
class CatalogLoadResult:
    catalog: ServiceCatalog
    issues: tuple[CatalogIssue, ...] = field(default=())

    @property
    def errors(self) -> tuple[CatalogIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[CatalogIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.WARNING)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_catalog(manifest: Manifest) -> CatalogLoadResult:
    """Load every declared service item and cross-check the corpus as a whole."""
    items: list[ServiceItem] = []
    issues: list[CatalogIssue] = []
    seen: dict[str, str] = {}

    for entry in manifest.of_type(DocType.SERVICE_ITEM):
        path = entry.path_in(manifest.directory)
        if not path.exists():
            issues.append(
                CatalogIssue(Severity.ERROR, entry.file, "declared in the manifest but not on disk")
            )
            continue

        try:
            parsed, document_issues = parse_service_document(
                path.read_text(encoding="utf-8"), entry.file
            )
        except (MalformedDocumentError, UnknownStatusCodeError) as exc:
            issues.append(CatalogIssue(Severity.ERROR, entry.file, str(exc).split(": ", 1)[-1]))
            continue

        issues.extend(document_issues)

        if parsed.item_id in seen:
            issues.append(
                CatalogIssue(
                    Severity.ERROR,
                    entry.file,
                    f"item id {parsed.item_id!r} already claimed by {seen[parsed.item_id]}",
                )
            )
            continue

        seen[parsed.item_id] = entry.file
        items.append(parsed)

    for undeclared in manifest.undeclared_files():
        issues.append(
            CatalogIssue(
                Severity.WARNING, undeclared, "present on disk but not declared in the manifest"
            )
        )

    catalog = ServiceCatalog.build(items)
    issues.extend(_cross_check(catalog))
    return CatalogLoadResult(catalog=catalog, issues=tuple(issues))


def _cross_check(catalog: ServiceCatalog) -> list[CatalogIssue]:
    """Checks that only make sense once every document has been read."""
    issues: list[CatalogIssue] = []

    # One status code should always carry one meaning. A document that words it
    # differently is either a typo or a genuine policy difference, and both are
    # worth a human deciding on.
    meanings: dict[Status, dict[str, list[str]]] = {}
    for item in catalog:
        if item.status_meaning:
            by_wording = meanings.setdefault(item.status, {})
            by_wording.setdefault(normalize_term(item.status_meaning), []).append(item.source)

    for status, wordings in meanings.items():
        if len(wordings) > 1:
            spread = "; ".join(
                f"{len(sources)} file(s) say {wording!r}" for wording, sources in wordings.items()
            )
            issues.append(
                CatalogIssue(
                    Severity.WARNING,
                    "<corpus>",
                    f"status {status.value!r} is described inconsistently: {spread}",
                )
            )

    for term, item_ids in catalog.alias_index.items():
        if len(item_ids) > 1:
            issues.append(
                CatalogIssue(
                    Severity.WARNING,
                    "<corpus>",
                    f"phrase {term!r} matches {len(item_ids)} items "
                    f"({', '.join(item_ids)}); the resolver will have to disambiguate",
                )
            )

    return issues
