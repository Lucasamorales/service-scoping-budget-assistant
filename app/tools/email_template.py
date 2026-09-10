"""Filling in the designed request-email templates.

The HTML and plain-text bodies are authored as files under
``app/assets/templates`` and carry ``{{token}}`` placeholders. Substitution is
a dictionary lookup and nothing more — there is no expression syntax, no
control flow and no template engine, which is what keeps a value typed by a
requester from ever being evaluated as markup.

Why ``{{token}}`` rather than ``str.format`` or an f-string: the templates are
inline-CSS email HTML, so they are full of literal ``{`` and ``}``. Either of
those mechanisms would need every brace in the file doubled, which makes the
templates unreadable to whoever edits them next and is a silent runtime error
the moment somebody forgets.

Every value is HTML-escaped on the way into the HTML body. Most of them are
system-generated, but the requester's name, role, branch and context are all
free text somebody typed into a web form, and escaping only the ones that look
dangerous is how the one that was overlooked gets through.
"""

from __future__ import annotations

import html
import re
from functools import cache
from pathlib import Path

__all__ = [
    "MISSING_TOKEN",
    "TEMPLATE_DIR",
    "known_kinds",
    "render_html",
    "render_text",
    "subject_for",
]

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "assets" / "templates"

MISSING_TOKEN = ""
"""What an absent token becomes.

Empty, not the literal placeholder. A recipient reading ``{{branch}}`` learns
nothing and distrusts the rest of the mail; a blank cell reads as "not
recorded", which is the truth.
"""

_TOKEN = re.compile(r"\{\{([a-z_]+)\}\}")

_SUBJECT_LINE = re.compile(r"\A\s*Subject:(?P<subject>.*)\n", re.MULTILINE)
"""The plain-text templates open with their own subject line.

Keeping it in the file means the wording lives with the rest of the copy the
designer wrote, instead of being restated in Python where the two would drift.
"""


@cache
def _template(kind: str, suffix: str) -> str:
    path = TEMPLATE_DIR / f"{kind}.{suffix}"
    if not path.is_file():
        raise FileNotFoundError(f"No {suffix} template for mail kind {kind!r}")
    return path.read_text(encoding="utf-8")


def known_kinds() -> frozenset[str]:
    """Mail kinds that have both a text and an HTML template on disk."""
    stems = {p.stem for p in TEMPLATE_DIR.glob("*.txt")}
    return frozenset(stem for stem in stems if (TEMPLATE_DIR / f"{stem}.html").is_file())


def _fill(template: str, values: dict[str, str], *, escape: bool) -> str:
    def swap(match: re.Match[str]) -> str:
        raw = values.get(match.group(1))
        if raw is None:
            return MISSING_TOKEN
        if not escape:
            return raw
        # quote=True so a value carrying a double quote cannot close an
        # attribute — several tokens land inside style="" and alt="".
        out = html.escape(raw, quote=True)
        # A requester types a paragraph with line breaks in it. Collapsing them
        # would run the sentences together; leaving them raw would show as one
        # line, because HTML does not honour a newline.
        return out.replace("\n", "<br>")

    return _TOKEN.sub(swap, template)


def subject_for(kind: str, values: dict[str, str]) -> str:
    """The subject line, read from the plain-text template's own header."""
    match = _SUBJECT_LINE.search(_template(kind, "txt"))
    if match is None:
        return ""
    return _fill(match.group("subject").strip(), values, escape=False)


def render_text(kind: str, values: dict[str, str]) -> str:
    """The plain-text body, with the ``Subject:`` header stripped off."""
    body = _SUBJECT_LINE.sub("", _template(kind, "txt"), count=1)
    return _fill(body, values, escape=False).strip() + "\n"


_DOC_COMMENT = re.compile(r"\A\s*<!--.*?-->\s*", re.DOTALL)
"""The token reference each template opens with.

Written for whoever edits the file, and stripped before substitution rather
than after: left in, it is filled with real values, so every email carried a
second invisible copy of the requester's context and about 1.5KB of comment.
"""

_EMPTY_IMG = re.compile(r"<img\b[^>]*\bsrc=\"\"[^>]*>", re.IGNORECASE)
_EMPTY_LINK = re.compile(r"<link\b[^>]*\bhref=\"\"[^>]*>\s*", re.IGNORECASE)
_FONT_FACES = re.compile(r"<style\b[^>]*>.*?</style>\s*", re.IGNORECASE | re.DOTALL)


def render_html(kind: str, values: dict[str, str]) -> str:
    """The HTML body. Every substituted value is escaped.

    An asset with no URL is removed rather than left with an empty one. Both
    are optional — the templates carry the whole hierarchy in text — but
    ``src=""`` is not the absence of an image: a mail client draws a broken
    icon for it, and one of those in the header band is worse than no logo at
    all. ``href=""`` on the stylesheet resolves to the document itself, which
    then gets fetched and parsed as CSS.
    """
    source = _DOC_COMMENT.sub("", _template(kind, "html"), count=1)
    html_body = _fill(source, values, escape=True)
    html_body = _EMPTY_IMG.sub("", html_body)
    if not values.get("font_css_url"):
        # The face declarations address the woff2 files absolutely, so with no
        # origin to address them from they would point at nothing. The only
        # <style> in these templates is that block — the design is otherwise
        # inline CSS throughout, which TestTheTemplatesStayEmailSafe holds to.
        html_body = _FONT_FACES.sub("", html_body)
    return _EMPTY_LINK.sub("", html_body)
