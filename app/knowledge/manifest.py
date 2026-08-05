"""The declared inventory of corpus documents.

Documents are declared, never discovered by globbing. Two reasons, both from
experience recorded in ``RAG-AND-TOOLING-TEMPLATE.md``:

* ``doc_type`` drives chunking strategy and retrieval filtering, and no
  heuristic reliably tells a service definition from a glossary from a set of
  pricing rules. It has to be author-declared.
* A file that quietly disappears from the corpus should fail the build, not
  shrink the knowledge base. A manifest entry with no file behind it is an
  error; a file with no manifest entry is a warning.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import CatalogError
from app.core.types import DocType

MANIFEST_FILENAME = "manifest.json"


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    file: str
    doc_type: DocType

    def path_in(self, directory: Path) -> Path:
        return directory / self.file


@dataclass(frozen=True, slots=True)
class Manifest:
    """Every document the corpus is expected to contain."""

    directory: Path
    entries: tuple[ManifestEntry, ...]

    def __iter__(self) -> Iterator[ManifestEntry]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def of_type(self, doc_type: DocType) -> tuple[ManifestEntry, ...]:
        return tuple(entry for entry in self.entries if entry.doc_type is doc_type)

    def undeclared_files(self) -> tuple[str, ...]:
        """Markdown files present on disk but absent from the manifest."""
        declared = {entry.file for entry in self.entries}
        found = {path.name for path in self.directory.glob("*.md")}
        return tuple(sorted(found - declared))

    @classmethod
    def load(cls, directory: Path) -> Manifest:
        manifest_path = directory / MANIFEST_FILENAME
        if not manifest_path.exists():
            raise CatalogError(
                f"No {MANIFEST_FILENAME} in {directory}. "
                f"Run `python -m scripts.generate_manifest` to create one."
            )

        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries: list[ManifestEntry] = []
        for index, record in enumerate(raw.get("documents", [])):
            try:
                entries.append(
                    ManifestEntry(file=record["file"], doc_type=DocType(record["docType"]))
                )
            except (KeyError, ValueError) as exc:
                raise CatalogError(f"{MANIFEST_FILENAME} entry {index} is invalid: {exc}") from exc

        if not entries:
            raise CatalogError(f"{MANIFEST_FILENAME} declares no documents.")

        return cls(directory=directory, entries=tuple(entries))
