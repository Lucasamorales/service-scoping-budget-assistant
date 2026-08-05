"""Create or refresh ``documents/manifest.json``.

Bootstrapping only. Once the manifest exists it is author-maintained: this
script preserves the ``docType`` already recorded for every known file, adds
newly discovered files as ``service_item``, and reports entries whose file has
disappeared rather than deleting them, so a missing document stays visible
instead of quietly shrinking the knowledge base.

    python -m scripts.generate_manifest
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.knowledge.manifest import MANIFEST_FILENAME, DocType

DEFAULT_DOCUMENTS_DIR = Path("documents")


def build_manifest(directory: Path) -> tuple[dict[str, object], list[str]]:
    manifest_path = directory / MANIFEST_FILENAME

    existing: dict[str, str] = {}
    if manifest_path.exists():
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        existing = {record["file"]: record["docType"] for record in raw.get("documents", [])}

    on_disk = sorted(path.name for path in directory.glob("*.md"))
    documents = [
        {"file": name, "docType": existing.get(name, DocType.SERVICE_ITEM.value)}
        for name in on_disk
    ]
    missing = sorted(set(existing) - set(on_disk))
    return {"documents": documents}, missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS_DIR)
    args = parser.parse_args()

    directory: Path = args.documents
    if not directory.is_dir():
        print(f"No such directory: {directory}")
        return 1

    manifest, missing = build_manifest(directory)
    destination = directory / MANIFEST_FILENAME
    destination.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    documents = manifest["documents"]
    assert isinstance(documents, list)
    print(f"Wrote {destination} with {len(documents)} documents.")

    counts: dict[str, int] = {}
    for record in documents:
        assert isinstance(record, dict)
        doc_type = str(record["docType"])
        counts[doc_type] = counts.get(doc_type, 0) + 1
    for doc_type, count in sorted(counts.items()):
        print(f"  {doc_type:16} {count}")

    if missing:
        print(f"\n{len(missing)} previously declared file(s) are no longer on disk:")
        for name in missing:
            print(f"  {name}")
        print("They have been dropped. Restore the file or accept the removal deliberately.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
