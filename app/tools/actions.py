"""Server-driven chat actions (Yes/No CTAs — never Form links)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["Action", "yes_no_actions"]

ActionKind = Literal["message", "link"]


@dataclass(frozen=True, slots=True)
class Action:
    id: str
    label: str
    kind: ActionKind
    message: str | None = None
    url: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "message": self.message,
            "url": self.url,
        }


def yes_no_actions(*, yes_label: str, no_label: str = "No thanks") -> tuple[Action, ...]:
    return (
        Action(id="confirm_yes", label=yes_label, kind="message", message="Yes"),
        Action(id="confirm_no", label=no_label, kind="message", message="No"),
    )
