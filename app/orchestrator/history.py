"""Prior turns carried by the client for wording continuity.

History never feeds the resolver. It only shapes how the model talks once the
scope fact for the current turn is already settled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["HISTORY_LINE_CHARS", "HistoryTurn", "format_history"]

HISTORY_LINE_CHARS = 800
"""Soft cap per line when packing history into the prompt."""


@dataclass(frozen=True, slots=True)
class HistoryTurn:
    role: Literal["user", "assistant"]
    content: str


def format_history(history: tuple[HistoryTurn, ...]) -> str:
    """Render prior turns for the model briefing."""
    lines: list[str] = []
    for turn in history:
        label = "User" if turn.role == "user" else "Assistant"
        text = turn.content.strip()
        if len(text) > HISTORY_LINE_CHARS:
            text = text[: HISTORY_LINE_CHARS - 1].rstrip() + "…"
        lines.append(f"{label}: {text}")
    return "\n".join(lines)
