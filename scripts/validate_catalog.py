"""Lint the service breakdown corpus and print what it actually contains.

Run this before trusting anything downstream, and run it in CI:

    python -m scripts.validate_catalog

Exits non-zero if any error was found. Errors mean a verdict somewhere cannot
be trusted, which is the one failure this system must never ship.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from app.core.errors import CatalogError
from app.core.types import Status
from app.knowledge.catalog import CatalogLoadResult, load_catalog
from app.knowledge.manifest import DocType, Manifest

DEFAULT_DOCUMENTS_DIR = Path("documents")

_STATUS_ORDER = (Status.IN_SCOPE, Status.QUOTE_REQUIRED, Status.LOCAL, Status.OUT_OF_SCOPE)


def _print_inventory(result: CatalogLoadResult) -> None:
    catalog = result.catalog
    print(f"Catalog: {len(catalog)} service items across {len(catalog.sections())} sections\n")

    by_status = Counter(item.status for item in catalog)
    print("By status")
    for status in _STATUS_ORDER:
        example = next((item for item in catalog if item.status is status), None)
        meaning = example.status_meaning if example else ""
        print(f"  {status.value:15} {by_status[status]:3}  {meaning}")

    print("\nBy section")
    by_section = Counter(item.section for item in catalog)
    for section, count in sorted(by_section.items()):
        breakdown = Counter(item.status for item in catalog if item.section == section)
        detail = ", ".join(
            f"{count} {status.value}" for status, count in breakdown.most_common() if count
        )
        print(f"  {section:48} {count:3}  ({detail})")

    ambiguous = sum(1 for ids in catalog.alias_index.values() if len(ids) > 1)
    print(f"\nSearch phrases: {len(catalog.alias_index)} total, {ambiguous} matching >1 item")


def _print_issues(result: CatalogLoadResult) -> None:
    if not result.issues:
        print("\nNo issues found.")
        return

    for label, issues in (("Errors", result.errors), ("Warnings", result.warnings)):
        if not issues:
            continue
        print(f"\n{label} ({len(issues)})")
        for issue in issues:
            print(f"  {issue.source}: {issue.message}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS_DIR)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as failures. Use once the corpus is clean.",
    )
    args = parser.parse_args()

    try:
        manifest = Manifest.load(args.documents)
    except CatalogError as exc:
        print(f"Could not load the manifest: {exc}")
        return 1

    declared = len(manifest.of_type(DocType.SERVICE_ITEM))
    print(f"Manifest declares {len(manifest)} documents, {declared} of them service items.")

    result = load_catalog(manifest)
    _print_inventory(result)
    _print_issues(result)

    if result.errors:
        print(f"\nFAILED: {len(result.errors)} error(s).")
        return 1
    if args.strict and result.warnings:
        print(f"\nFAILED: {len(result.warnings)} warning(s) under --strict.")
        return 1

    print(f"\nPASSED with {len(result.warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
