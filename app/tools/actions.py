"""Server-driven chat actions (Yes/No CTAs — never Form links)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["Action", "yes_no_actions"]

ActionKind = Literal["message", "link", "note"]


@dataclass(frozen=True, slots=True)
class Action:
    id: str
    label: str
    kind: ActionKind
    message: str | None = None
    url: str | None = None

    prompt: str | None = None
    """What to ask for, on a ``note`` action.

    A ``note`` action does not fire on click. The client opens a box, and what
    is typed travels beside the confirmation rather than as it — the message
    stays "Yes" so the affirmative check keeps meaning what it says.
    """

    placeholder: str | None = None
    """An example of a useful answer. Concrete beats instructions: people copy
    the shape of what they are shown."""

    def as_dict(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "message": self.message,
            "url": self.url,
            "prompt": self.prompt,
            "placeholder": self.placeholder,
        }


def yes_no_actions(
    *,
    yes_label: str,
    no_label: str = "No thanks",
    prompt: str | None = None,
    placeholder: str | None = None,
) -> tuple[Action, ...]:
    """The pair offered under a reply that can send an email.

    With a ``prompt`` the yes becomes a ``note`` action: the client asks for
    context first and sends it alongside the confirmation. Without one it fires
    straight away, which is what every other CTA still does.
    """
    return (
        Action(
            id="confirm_yes",
            label=yes_label,
            kind="note" if prompt else "message",
            message="Yes",
            prompt=prompt,
            placeholder=placeholder,
        ),
        Action(id="confirm_no", label=no_label, kind="message", message="No"),
    )
