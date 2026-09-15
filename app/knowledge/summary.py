"""One sentence on what a service is, taken from its own document.

Three places need it — the line under a verdict, the service list, and the
options offered when the resolver has to ask — and it lived as two identical
copies before the third arrived. One implementation, so the same service is
never described two different ways on the same screen.
"""

from __future__ import annotations

import re

from app.core.types import ServiceItem

__all__ = ["one_line"]

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

_MIN_CHARS = 45
"""Below this a "sentence" is almost certainly an abbreviation.

Splitting on ". " alone reduced "Int. goals dashboards provide a visual
representation of..." to the word "Int.", which is worse than no description.
Short pieces are joined to the next one until the result reads as a sentence."""

_MAX_CHARS = 190
"""Longer than this stops being a glance and becomes a paragraph. Cut on a word
boundary."""


def one_line(item: ServiceItem) -> str:
    """The opening sentence of what the document says this service covers.

    Takes "What This Item Covers" rather than the document's own Summary: the
    Summary restates the section and the verdict — "is part of X, meaning it is
    included in our services" — which whatever sits beside this has already
    said. A whole section runs to a paragraph; its first sentence is reliably
    the definition, and the rest qualifies it.
    """
    body = (item.sections.get("What This Item Covers") or item.summary).strip()
    if not body:
        return ""
    out = ""
    for piece in _SENTENCE_END.split(body):
        out = f"{out} {piece}".strip() if out else piece
        if len(out) >= _MIN_CHARS:
            break
    if len(out) > _MAX_CHARS:
        out = out[:_MAX_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return out
