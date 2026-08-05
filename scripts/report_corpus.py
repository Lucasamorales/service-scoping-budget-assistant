"""Print raw statistics about the corpus files themselves.

Used to size the chunker against reality rather than assumption, and to catch
encoding damage before it reaches retrieval. Mojibake is retrieval-visible: a
chunk containing a broken apostrophe fails a keyword match on the word it
belongs to.

    python -m scripts.report_corpus
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from collections import Counter
from pathlib import Path

DEFAULT_DOCUMENTS_DIR = Path("documents")

# Byte sequences that appear when UTF-8 is decoded as Latin-1 somewhere upstream.
MOJIBAKE_MARKERS = ("\u00e2\u0080", "\u00c3\u00a9", "\u00c2\u00a3", "\u00c3\u00b1")

BACKSLASH_ESCAPE_RE = re.compile(r"\\(.)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS_DIR)
    args = parser.parse_args()

    paths = sorted(args.documents.glob("*.md"))
    if not paths:
        print(f"No markdown found in {args.documents}")
        return 1

    texts = {path.name: path.read_text(encoding="utf-8") for path in paths}
    lengths = sorted((len(text), name) for name, text in texts.items())

    print(f"{len(paths)} documents")
    print(
        f"  characters: min {lengths[0][0]}, "
        f"median {lengths[len(lengths) // 2][0]}, "
        f"max {lengths[-1][0]}, "
        f"total {sum(length for length, _ in lengths)}"
    )
    print("\n  largest:")
    for length, name in reversed(lengths[-3:]):
        print(f"    {length:6}  {name}")
    print("  smallest:")
    for length, name in lengths[:3]:
        print(f"    {length:6}  {name}")

    damaged = [name for name, text in texts.items() if any(m in text for m in MOJIBAKE_MARKERS)]
    print(f"\nMojibake: {len(damaged)} file(s)")
    for name in damaged:
        print(f"    {name}")

    non_ascii: Counter[str] = Counter()
    for text in texts.values():
        non_ascii.update(char for char in text if ord(char) > 127)
    print(f"\nNon-ASCII characters in use: {len(non_ascii)} distinct")
    for char, count in non_ascii.most_common():
        print(f"    {char!r:10} {unicodedata.name(char, 'UNNAMED'):32} {count}")

    escapes: Counter[str] = Counter()
    for text in texts.values():
        escapes.update(BACKSLASH_ESCAPE_RE.findall(text))
    print(f"\nBackslash escapes: {sum(escapes.values())}")
    for char, count in escapes.most_common(10):
        print(f"    \\{char}  {count}")

    empty_headings = sum(
        len(re.findall(r"^#{1,6}\s*$", text, re.MULTILINE)) for text in texts.values()
    )
    print(f"\nEmpty headings: {empty_headings}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
