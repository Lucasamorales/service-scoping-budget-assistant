"""Conversation transcript for AM/CM email attachments.

The live chat only keeps a short tail of the thread, so the email never uses
that as the source of truth. We read the audit log (Firestore or JSONL), which
has every turn unclipped, and fall back to the client history only when the
log is empty. The PDF is for the person receiving the request; a plain-text
file is the fallback if PDF generation fails.

The PDF is laid out to the design handoff: A4, a navy cover band, a summary
grid, and the conversation as inset blocks — the requester indented and filled,
the assistant flush and outlined. Positions are millimetres, type sizes points.

Brand faces are embedded from ``app/assets/fonts``. That is also what let the
old ``_pdf_safe``/cp1252 pass go: the core fonts fpdf2 falls back on are
Latin-1, and the pound sign survived only because cp1252 happens to contain it.
An embedded TrueType font is Unicode, so ``£``, ``—`` and curly quotes now
render as typed rather than as ``?``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog
from fpdf import FPDF
from fpdf.enums import MethodReturnValue, XPos, YPos

from app.core.types import ServiceItem
from app.orchestrator.history import HistoryTurn
from app.store.audit import AuditEvent, AuditStore

__all__ = [
    "TranscriptTurn",
    "build_transcript",
    "render_transcript_pdf",
    "render_transcript_text",
    "transcript_attachment",
]

logger = structlog.get_logger(__name__)

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_FONTS = _ASSETS / "fonts"
_LOGO = _ASSETS / "acme-logo-white.png"

_UI = "Inter"
_DISPLAY = "United"

# Millimetres. The text column is what is left of A4 between the margins.
_PAGE_W = 210.0
_MARGIN_L = 20.0
_MARGIN_R = 20.0
_COLUMN = _PAGE_W - _MARGIN_L - _MARGIN_R
_RIGHT = _PAGE_W - _MARGIN_R
_BODY_BOTTOM = 274.0
"""Below this a block goes to the next page whole. The footer rule is at 282.5,
and a block that ends flush against it reads as though it was cut off."""

_PAGE_TOP = 27.5
"""Where content starts on a continuation page, under its running header."""

_END_MATTER = 17.0
"""Room the closing rule and line need.

Reserved against the *last* block rather than checked afterwards. Checking
afterwards is what left a page carrying nothing but "END OF CONVERSATION": the
conversation had filled page one to within a few millimetres, so the only thing
that moved was the line announcing it had finished."""

_NAVY = (0x23, 0x2F, 0x55)
_DEEP = (0x14, 0x21, 0x3B)
_BODY = (0x2C, 0x3D, 0x50)
_MUTED = (0x5A, 0x6E, 0x85)
_FAINT = (0x8A, 0x9B, 0xAD)
_TINT = (0xF0, 0xF4, 0xF8)
_RULE = (0xD7, 0xE0, 0xEA)
_HAIR = (0xE8, 0xEE, 0xF4)
_BAND_LABEL = (0x8F, 0xA3, 0xC8)

_LABEL_DROP = 4.3
"""Top of a grid label to top of its value: the 8pt label is 2.8mm tall and the
design puts 1.5mm under it."""
_WHITE = (0xFF, 0xFF, 0xFF)

_PILL = {
    "quote_required": ((0x1D, 0x5D, 0x8C), (0xE7, 0xF1, 0xF9), (0xA9, 0xCF, 0xE8)),
    "in_scope": ((0x1F, 0x7A, 0x4D), (0xE6, 0xF5, 0xEC), (0xA9, 0xDC, 0xC1)),
    "local": ((0xA6, 0x74, 0x1A), (0xFB, 0xF2, 0xE0), (0xE4, 0xC8, 0x8A)),
    "out_of_scope": ((0x6E, 0x5A, 0x4E), (0xF2, 0xED, 0xE9), (0xD8, 0xC8, 0xBC)),
}

_PILL_LABEL = {
    "quote_required": "QUOTE REQUIRED",
    "in_scope": "IN SCOPE",
    "local": "LOCAL",
    "out_of_scope": "OUT OF SCOPE",
}

_DECISION = {
    "email_cm_po": "PURCHASE ORDER REQUESTED",
    "email_am": "IN SCOPE — NO CHARGE",
    "email_am_variable": "NOT ON THE RATE CARD",
    "email_am_out_of_scope": "ASKING FOR ANOTHER WAY",
}


@dataclass(frozen=True, slots=True)
class TranscriptTurn:
    at: str
    role: str
    content: str
    verdict: str | None = None
    """The turn's own scope verdict, when it reached one.

    Most turns do not. A budget answer, a clarifying question and a greeting
    all resolve no service, so they carry nothing and render with no pill —
    which is the normal case, not a degraded one.
    """


def build_transcript(
    *,
    conversation_id: str | None,
    audit_log: AuditStore | None,
    history: tuple[HistoryTurn, ...] = (),
    current_message: str | None = None,
) -> tuple[TranscriptTurn, ...]:
    """Prefer the audit log; use client history only when nothing was stored.

    ``current_message`` is the message being handled right now. It has to be
    passed in because the attachment is built while the turn is still running —
    the audit row for it does not exist yet — and without it the PDF stops one
    message short of the "Yes" that authorised the email.
    """
    turns: tuple[TranscriptTurn, ...] = ()
    if conversation_id and audit_log is not None:
        turns = _from_audit(audit_log.read(conversation_id))
    if not turns:
        turns = _from_history(history)

    pending = (current_message or "").strip()
    if not pending or (
        turns and turns[-1].role == "user" and turns[-1].content.strip() == pending
    ):
        return turns
    return (*turns, TranscriptTurn(at="", role="user", content=pending))


def render_transcript_text(
    turns: tuple[TranscriptTurn, ...],
    *,
    title: str,
    requester: str | None = None,
    country: str | None = None,
    branch: str | None = None,
    service: str | None = None,
    conversation_id: str | None = None,
    **_ignored: object,
) -> str:
    lines = [title, ""]
    lines.extend(
        _meta_lines(
            requester=requester,
            country=country,
            branch=branch,
            service=service,
            conversation_id=conversation_id,
        )
    )
    lines.append("")
    lines.append("Conversation")
    lines.append("------------")
    if not turns:
        lines.append("(No earlier messages were stored for this chat.)")
        return "\n".join(lines)
    for turn in turns:
        who = "You" if turn.role == "user" else "Assistant"
        when = f"  ({_short_time(turn.at)} UTC)" if turn.at else ""
        lines.append("")
        lines.append(f"{who}{when}")
        lines.append(turn.content.strip() or "(empty)")
    return "\n".join(lines)


class _TranscriptPDF(FPDF):
    """Carries the running header and footer the design asks for.

    Both need values from the request, so they live on the instance rather than
    in a closure — ``footer`` is called by fpdf2 during ``add_page``.
    """

    def __init__(self, *, reference: str, continued: str) -> None:
        super().__init__(format="A4")
        self.reference = reference
        self.continued = continued
        self.cover_done = False

    def header(self) -> None:
        # Page one gets the navy band instead, drawn by the caller once the
        # fonts are registered; this is every page after it.
        if not self.cover_done:
            return
        _text(self, _MARGIN_L, 16, self.continued, size=8, colour=_FAINT)
        _text(
            self,
            _RIGHT,
            16,
            "CONVERSATION CONTINUED · ALL TIMES UTC",
            size=8,
            colour=_FAINT,
            align="R",
        )
        _rule(self, 21.5)
        self.set_xy(_MARGIN_L, _PAGE_TOP)

    def footer(self) -> None:
        _rule(self, 282.5, colour=_HAIR)
        _text(self, _MARGIN_L, 286.5, f"Page {self.page_no()} of {{nb}}", size=7.5, colour=_FAINT)
        if self.reference:
            _text(self, _RIGHT, 286.5, self.reference, size=7.5, colour=_FAINT, align="R")


def render_transcript_pdf(
    turns: tuple[TranscriptTurn, ...],
    *,
    title: str,
    requester: str | None = None,
    role: str | None = None,
    country: str | None = None,
    branch: str | None = None,
    service: str | None = None,
    item: ServiceItem | None = None,
    recipient: str | None = None,
    amount: str = "",
    note: str | None = None,
    kind: str = "",
    conversation_id: str | None = None,
) -> bytes:
    """The request record: a cover, then the conversation that produced it."""
    verdict = item.status.value if item else None
    service_name = item.item if item else (service or "A marketing request")
    section = item.section if item else ""
    where = ", ".join(part for part in (branch, country) if part)

    pdf = _TranscriptPDF(
        reference=conversation_id or "",
        continued=" · ".join(part for part in (service, branch) if part),
    )
    _register_fonts(pdf)
    pdf.set_margins(left=_MARGIN_L, top=16, right=_MARGIN_R)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_title(title[:200])
    pdf.add_page()

    # --- cover band -------------------------------------------------------
    pdf.set_fill_color(*_NAVY)
    pdf.rect(0, 0, _PAGE_W, 34, style="F")
    if _LOGO.is_file():
        pdf.image(str(_LOGO), x=_MARGIN_L, y=12.5, h=9)
    _text(
        pdf,
        _RIGHT,
        14.8,
        "SCOPING ASSISTANT · REQUEST RECORD",
        size=8,
        colour=_BAND_LABEL,
        bold=True,
        align="R",
        spacing=1.1,
    )

    # --- verdict ----------------------------------------------------------
    width = _pill(pdf, _MARGIN_L, 43, verdict, height=5.6, size=7.5, radius=2.8, pad=3)
    decision = _DECISION.get(kind, "")
    if decision:
        _text(pdf, _MARGIN_L + width + 4, 43 + (5.6 - _mm(8)) / 2, decision, size=8, colour=_FAINT)

    _text(pdf, _MARGIN_L, 52, service_name.upper(), size=26, colour=_DEEP, display=True)
    subtitle = " · ".join(part for part in (section, where) if part)
    _text(pdf, _MARGIN_L, 63.5, subtitle, size=10.5, colour=_MUTED)
    _rule(pdf, 72)

    # --- summary grid -----------------------------------------------------
    columns = (_MARGIN_L, 78.7, 137.3)
    rows = (
        (
            ("REQUESTER", ", ".join(p for p in (requester, role) if p)),
            ("SERVICE", service or ""),
            ("STATUS", item.status_raw.strip() if item else ""),
        ),
        (
            ("AMOUNT", amount or "—"),
            ("SENT TO", recipient or ""),
            ("ASKED", _asked_on(turns)),
        ),
    )
    for index, row in enumerate(rows):
        top = 77.0 + index * 16.0
        for column, (label, value) in zip(columns, row, strict=True):
            _text(pdf, column, top, label, size=8, colour=_FAINT, spacing=0.6)
            if label == "AMOUNT" and value != "—":
                _text(pdf, column, top + _LABEL_DROP, value, size=16, colour=_DEEP, display=True)
            else:
                _wrap(
                    pdf, column, top + _LABEL_DROP, 52.7, value,
                    size=10.5, colour=_BODY, leading=5.2,
                )

    # --- why they are asking ---------------------------------------------
    y = 109.0
    context = (note or "").strip()
    if context:
        height = _wrap(
            pdf, _MARGIN_L + 6, y + 12.2, _COLUMN - 12, context,
            size=11, colour=_DEEP, leading=4.3, measure=True,
        )
        block = 12.2 + height + 5
        pdf.set_fill_color(*_TINT)
        pdf.rect(_MARGIN_L, y, _COLUMN, block, style="F")
        _text(pdf, _MARGIN_L + 6, y + 5, "WHY THEY ARE ASKING", size=8, colour=_MUTED, bold=True)
        _wrap(
            pdf, _MARGIN_L + 6, y + 12.2, _COLUMN - 12, context,
            size=11, colour=_DEEP, leading=4.3,
        )
        y += block

    # --- the conversation -------------------------------------------------
    pdf.cover_done = True
    y += 6
    y = _conversation_heading(pdf, y, _date_label(turns))

    if not turns:
        _wrap(pdf, _MARGIN_L, y + 2, _COLUMN, "(No earlier messages were stored for this chat.)",
              size=11, colour=_FAINT)
    else:
        y = _draw_turns(pdf, y, turns)
        _rule(pdf, y + 6, colour=_HAIR)
        _text(
            pdf,
            _MARGIN_L,
            y + 11,
            f"END OF CONVERSATION · {len(turns)} MESSAGES · "
            f"REQUEST SENT {datetime.now(UTC).strftime('%H:%M')} UTC",
            size=8,
            colour=_FAINT,
        )

    return bytes(pdf.output())


def _draw_turns(pdf: _TranscriptPDF, y: float, turns: tuple[TranscriptTurn, ...]) -> float:
    """Lay the blocks down the page, breaking between them rather than inside."""
    seen_date = _date_label(turns)
    last = len(turns) - 1
    for index, turn in enumerate(turns):
        date = _date_of(turn.at)
        if date and date != seen_date:
            seen_date = date
            y = _conversation_heading(pdf, y + 4, date, first=False)

        is_user = turn.role == "user"
        left = 46.0 if is_user else _MARGIN_L
        width = 144.0
        body = turn.content.strip() or "(empty)"
        text_h = _wrap(
            pdf, left + 6, y, width - 12, body,
            size=11, colour=_DEEP if is_user else _BODY, leading=4.3, measure=True,
        )
        block = 4.5 + 3.5 + 2 + text_h + 4.5

        # The last block carries the closing line with it, so the two never end
        # up on separate pages.
        needed = block + (_END_MATTER if index == last else 0)
        fits_on_a_fresh_page = needed <= _BODY_BOTTOM - _PAGE_TOP
        if y + needed > _BODY_BOTTOM and fits_on_a_fresh_page:
            pdf.add_page()
            y = _PAGE_TOP

        if is_user:
            pdf.set_fill_color(*_TINT)
            pdf.rect(left, y, width, block, style="F")
        else:
            pdf.set_draw_color(*_RULE)
            pdf.set_line_width(0.25)
            pdf.set_fill_color(*_WHITE)
            pdf.rect(left, y, width, block, style="DF")

        name = "REQUESTER" if is_user else "SCOPING ASSISTANT"
        _text(pdf, left + 6, y + 4.5, name, size=8,
              colour=_DEEP if is_user else _MUTED, bold=True, spacing=0.6)
        if not is_user and turn.verdict:
            offset = pdf.get_string_width(name) + 0.6 * len(name)
            _pill(pdf, left + 6 + offset + 3, y + 4.5 - (4 - _mm(8)) / 2, turn.verdict,
                  height=4, size=7, radius=2, pad=2.4)
        if turn.at:
            _text(pdf, left + width - 6, y + 4.5, f"{_short_time(turn.at)}",
                  size=8, colour=_FAINT, align="R")

        _wrap(pdf, left + 6, y + 4.5 + 3.5 + 2, width - 12, body,
              size=11, colour=_DEEP if is_user else _BODY, leading=4.3)
        y += block + 4
    return y


def _conversation_heading(pdf: _TranscriptPDF, y: float, date: str, *, first: bool = True) -> float:
    """The label, its date note, and a rule filling the rest of the line."""
    label = "CONVERSATION" if first else date.upper()
    tall = _mm(13)
    _text(pdf, _MARGIN_L, y, label, size=13, colour=_DEEP, display=True)
    used = pdf.get_string_width(label)
    if first:
        note = f"{date.upper()} · ALL TIMES UTC" if date else "ALL TIMES UTC"
        # Centred on the big label rather than sharing its top, so the two read
        # as one line instead of as a heading with something stuck above it.
        _text(pdf, _MARGIN_L + used + 4, y + (tall - _mm(8)) / 2, note, size=8, colour=_FAINT)
        used += 4 + pdf.get_string_width(note)
    start = _MARGIN_L + used + 4
    if start < _RIGHT:
        pdf.set_draw_color(*_HAIR)
        pdf.set_line_width(0.25)
        pdf.line(start, y + tall / 2, _RIGHT, y + tall / 2)
    return y + tall + 5


# ---------------------------------------------------------------- drawing --


def _register_fonts(pdf: FPDF) -> None:
    """Embed the brand faces, falling back to the core fonts if they are absent.

    A missing font file must not stop an email going out, so this degrades to
    Helvetica rather than raising. The layout is unchanged either way — only
    the letterforms differ.
    """
    faces = (
        (_UI, "", "Inter-Regular.ttf"),
        (_UI, "B", "Inter-Bold.ttf"),
        (_DISPLAY, "", "InterDisplay-Black.ttf"),
    )
    for family, style, filename in faces:
        path = _FONTS / filename
        if not path.is_file():
            logger.warning("transcript.font_missing", font=filename)
            continue
        pdf.add_font(family, style, str(path))


def _mm(points: float) -> float:
    """Type size in millimetres — one point is 1/72 inch, one inch is 25.4mm."""
    return points * 25.4 / 72


def _has(pdf: FPDF, family: str) -> bool:
    """Whether a family actually registered.

    fpdf2 keys its registry by the lowercased family name, so testing for
    ``"Inter"`` silently missed every time and the whole document quietly fell
    back to Helvetica — which is Latin-1, so an em dash then raised mid-render
    and the email went out with a .txt attachment instead of the PDF.
    """
    return family.lower() in pdf.fonts


def _face(pdf: FPDF, *, display: bool, bold: bool) -> tuple[str, str]:
    if display and _has(pdf, _DISPLAY):
        return _DISPLAY, ""
    if _has(pdf, _UI):
        return _UI, "B" if bold or display else ""
    return "Helvetica", "B" if bold or display else ""


def _text(
    pdf: FPDF,
    x: float,
    y: float,
    value: str,
    *,
    size: float,
    colour: tuple[int, int, int],
    bold: bool = False,
    display: bool = False,
    align: str = "L",
    spacing: float = 0.0,
) -> None:
    """One line, never wrapped. ``y`` is the top of the type, not its baseline.

    The design handoff is a table of y positions, and every one of them is
    where the element starts. Anchoring on the baseline instead put each
    heading a full cap-height too high, which is what drove the verdict pill
    underneath the service name.
    """
    if not value:
        return
    family, style = _face(pdf, display=display, bold=bold)
    pdf.set_font(family, style, size)
    pdf.set_text_color(*colour)
    if spacing:
        pdf.set_char_spacing(spacing)
    width = pdf.get_string_width(value) + spacing * len(value)
    left = x - width if align == "R" else x
    pdf.set_xy(left, y)
    pdf.cell(width + 1, _mm(size), value, new_x=XPos.LMARGIN, new_y=YPos.TOP)
    if spacing:
        pdf.set_char_spacing(0)


def _wrap(
    pdf: FPDF,
    x: float,
    y: float,
    width: float,
    value: str,
    *,
    size: float,
    colour: tuple[int, int, int],
    leading: float = 4.3,
    measure: bool = False,
) -> float:
    """A wrapped paragraph. Returns its height; ``measure`` draws nothing.

    Measuring before drawing is what lets a fill or a border be sized to text
    that has not been written yet — fpdf2 has no way to grow a rect after the
    fact.
    """
    if not value:
        return 0.0
    family, style = _face(pdf, display=False, bold=False)
    pdf.set_font(family, style, size)
    pdf.set_text_color(*colour)
    pdf.set_xy(x, y)
    # HEIGHT alone is requested, so fpdf2 returns the float — the union in its
    # signature covers the other output combinations.
    height = pdf.multi_cell(
        width,
        leading,
        value,
        align="L",
        dry_run=measure,
        output=MethodReturnValue.HEIGHT,
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    assert isinstance(height, (int, float))
    return float(height)


def _rule(pdf: FPDF, y: float, *, colour: tuple[int, int, int] = _RULE) -> None:
    pdf.set_draw_color(*colour)
    pdf.set_line_width(0.25)
    pdf.line(_MARGIN_L, y, _RIGHT, y)


def _pill(
    pdf: FPDF,
    x: float,
    y: float,
    verdict: str | None,
    *,
    height: float,
    size: float,
    radius: float,
    pad: float,
) -> float:
    """A rounded verdict chip. Returns its width, or zero when there is none."""
    if not verdict or verdict not in _PILL:
        return 0.0
    text_colour, fill, border = _PILL[verdict]
    label = _PILL_LABEL[verdict]
    family, style = _face(pdf, display=False, bold=True)
    pdf.set_font(family, style, size)
    spacing = 0.7 if height > 5 else 0.5
    width = pdf.get_string_width(label) + spacing * len(label) + pad * 2

    pdf.set_fill_color(*fill)
    pdf.set_draw_color(*border)
    pdf.set_line_width(0.25)
    pdf.rect(x, y, width, height, style="DF", round_corners=True, corner_radius=radius)
    _text(
        pdf,
        x + pad,
        y + (height - _mm(size)) / 2,
        label,
        size=size,
        colour=text_colour,
        bold=True,
        spacing=spacing,
    )
    return width


# ------------------------------------------------------------- attachment --


def transcript_attachment(
    turns: tuple[TranscriptTurn, ...],
    *,
    title: str,
    filename_stem: str,
    **details: object,
) -> tuple[str, bytes, str]:
    """``(filename, bytes, mime)``. PDF preferred; plain text if rendering fails."""
    try:
        data = render_transcript_pdf(turns, title=title, **details)  # type: ignore[arg-type]
        if data.startswith(b"%PDF"):
            return f"{filename_stem}.pdf", data, "application/pdf"
        raise ValueError("PDF renderer returned a file that is not a PDF")
    except Exception as exc:  # noqa: BLE001
        logger.warning("transcript.pdf_failed", error=str(exc))
        text = render_transcript_text(turns, title=title, **details)  # type: ignore[arg-type]
        return f"{filename_stem}.txt", text.encode("utf-8"), "text/plain"


# ------------------------------------------------------------------ input --


def _from_audit(events: list[AuditEvent]) -> tuple[TranscriptTurn, ...]:
    turns: list[TranscriptTurn] = []
    for event in events:
        if event.kind != "turn":
            continue
        payload = event.payload
        user = str(payload.get("user_message") or "").strip()
        assistant = str(payload.get("assistant_message") or "").strip()
        at = event.at or str(payload.get("at") or "")
        status = payload.get("status")
        if user:
            turns.append(TranscriptTurn(at=at, role="user", content=user))
        if assistant:
            turns.append(
                TranscriptTurn(
                    at=at,
                    role="assistant",
                    content=assistant,
                    verdict=str(status) if status else None,
                )
            )
    return tuple(turns)


def _from_history(history: tuple[HistoryTurn, ...]) -> tuple[TranscriptTurn, ...]:
    """The client's copy, which carries no verdicts — it never held any."""
    return tuple(
        TranscriptTurn(at="", role=turn.role, content=turn.content.strip())
        for turn in history
        if turn.content.strip()
    )


def _meta_lines(
    *,
    requester: str | None,
    country: str | None,
    branch: str | None,
    service: str | None,
    conversation_id: str | None,
) -> list[str]:
    return [
        f"From: {requester or 'unknown'}",
        f"Country: {country or 'unknown'}",
        f"Branch: {branch or 'unknown'}",
        f"Service: {service or 'unknown'}",
        f"Reference: {conversation_id or 'unknown'}",
    ]


def _short_time(raw: str) -> str:
    if not raw:
        return ""
    # ISO timestamps: 2026-08-20T16:01:02.123+00:00 → 16:01
    stamp = raw.replace("T", " ")
    return stamp[11:16] if len(stamp) >= 16 else stamp


def _date_of(raw: str) -> str:
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(raw).strftime("%A %d %B %Y")
    except ValueError:
        return ""


def _date_label(turns: tuple[TranscriptTurn, ...]) -> str:
    for turn in turns:
        label = _date_of(turn.at)
        if label:
            return label
    return datetime.now(UTC).strftime("%A %d %B %Y")


def _asked_on(turns: tuple[TranscriptTurn, ...]) -> str:
    for turn in turns:
        if turn.at:
            try:
                return datetime.fromisoformat(turn.at).strftime("%d %b %Y, %H:%M UTC")
            except ValueError:
                continue
    return datetime.now(UTC).strftime("%d %b %Y, %H:%M UTC")
