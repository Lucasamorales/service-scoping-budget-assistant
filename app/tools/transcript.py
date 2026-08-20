"""Conversation transcript for AM/CM email attachments.

The live chat only keeps a short tail of the thread, so the email never uses
that as the source of truth. We read the audit log (Firestore or JSONL), which
has every turn unclipped, and fall back to the client history only when the
log is empty. The PDF is for the person receiving the request; a plain-text
file is the fallback if PDF generation fails.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from fpdf import FPDF

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

_WINANSI = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
        "\u00a0": " ",
        "\u2022": "-",
    }
)


@dataclass(frozen=True, slots=True)
class TranscriptTurn:
    at: str
    role: str
    content: str


def build_transcript(
    *,
    conversation_id: str | None,
    audit_log: AuditStore | None,
    history: tuple[HistoryTurn, ...] = (),
) -> tuple[TranscriptTurn, ...]:
    """Prefer the audit log; use client history only when nothing was stored."""
    if conversation_id and audit_log is not None:
        from_log = _from_audit(audit_log.read(conversation_id))
        if from_log:
            return from_log
    return _from_history(history)


def render_transcript_text(
    turns: tuple[TranscriptTurn, ...],
    *,
    title: str,
    requester: str | None = None,
    country: str | None = None,
    branch: str | None = None,
    service: str | None = None,
    conversation_id: str | None = None,
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
        when = f"  ({_short_time(turn.at)})" if turn.at else ""
        lines.append("")
        lines.append(f"{who}{when}")
        lines.append(turn.content.strip() or "(empty)")
    return "\n".join(lines)


def render_transcript_pdf(
    turns: tuple[TranscriptTurn, ...],
    *,
    title: str,
    requester: str | None = None,
    country: str | None = None,
    branch: str | None = None,
    service: str | None = None,
    conversation_id: str | None = None,
) -> bytes:
    """A readable one-column PDF. Core fonts only, so punctuation is normalised."""

    class _TranscriptPDF(FPDF):
        def footer(self) -> None:
            self.set_y(-15)
            self.set_x(self.l_margin)
            self.set_font("Helvetica", "I", 8)
            ref = conversation_id or ""
            self.cell(0, 10, _pdf_safe(f"Page {self.page_no()}    {ref}"), align="C")

    pdf = _TranscriptPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_title(_pdf_safe(title)[:200])

    pdf.set_font("Helvetica", "B", 16)
    _pdf_write(pdf, _pdf_safe(title), height=8)
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 11)
    meta = "\n".join(
        _meta_lines(
            requester=requester,
            country=country,
            branch=branch,
            service=service,
            conversation_id=conversation_id,
        )
    )
    _pdf_write(pdf, _pdf_safe(meta), height=6)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 12)
    _pdf_write(pdf, "Conversation", height=7)
    pdf.ln(1)

    if not turns:
        pdf.set_font("Helvetica", "I", 11)
        _pdf_write(pdf, "(No earlier messages were stored for this chat.)", height=6)
    else:
        for turn in turns:
            who = "You" if turn.role == "user" else "Assistant"
            when = _short_time(turn.at)
            label = f"{who}  {when}".strip()
            pdf.set_font("Helvetica", "B", 11)
            _pdf_write(pdf, _pdf_safe(label), height=6)
            pdf.set_font("Helvetica", "", 11)
            _pdf_write(pdf, _pdf_safe(turn.content.strip() or "(empty)"), height=6)
            pdf.ln(3)

    return bytes(pdf.output())


def transcript_attachment(
    turns: tuple[TranscriptTurn, ...],
    *,
    title: str,
    filename_stem: str,
    requester: str | None = None,
    country: str | None = None,
    branch: str | None = None,
    service: str | None = None,
    conversation_id: str | None = None,
) -> tuple[str, bytes, str]:
    """``(filename, bytes, mime)``. PDF preferred; plain text if rendering fails."""
    try:
        data = render_transcript_pdf(
            turns,
            title=title,
            requester=requester,
            country=country,
            branch=branch,
            service=service,
            conversation_id=conversation_id,
        )
        if data.startswith(b"%PDF"):
            return f"{filename_stem}.pdf", data, "application/pdf"
        raise ValueError("PDF renderer returned a file that is not a PDF")
    except Exception as exc:  # noqa: BLE001
        logger.warning("transcript.pdf_failed", error=str(exc))
        text = render_transcript_text(
            turns,
            title=title,
            requester=requester,
            country=country,
            branch=branch,
            service=service,
            conversation_id=conversation_id,
        )
        return f"{filename_stem}.txt", text.encode("utf-8"), "text/plain"


def _from_audit(events: list[AuditEvent]) -> tuple[TranscriptTurn, ...]:
    turns: list[TranscriptTurn] = []
    for event in events:
        if event.kind != "turn":
            continue
        payload = event.payload
        user = str(payload.get("user_message") or "").strip()
        assistant = str(payload.get("assistant_message") or "").strip()
        at = event.at or str(payload.get("at") or "")
        if user:
            turns.append(TranscriptTurn(at=at, role="user", content=user))
        if assistant:
            turns.append(TranscriptTurn(at=at, role="assistant", content=assistant))
    return tuple(turns)


def _from_history(history: tuple[HistoryTurn, ...]) -> tuple[TranscriptTurn, ...]:
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
    # ISO timestamps: 2026-08-20T16:01:02.123+00:00 → 2026-08-20 16:01
    stamp = raw.replace("T", " ")
    if len(stamp) >= 16:
        return stamp[:16]
    return stamp


def _pdf_write(pdf: FPDF, text: str, *, height: float) -> None:
    """Write a paragraph and return the cursor to the left margin.

    fpdf2's multi_cell leaves X at the right of the last line, so the next
    call would have zero remaining width unless we reset it.
    """
    pdf.multi_cell(0, height, text, new_x="LMARGIN", new_y="NEXT")


def _pdf_safe(text: str) -> str:
    cleaned = (text or "").translate(_WINANSI).replace("\r\n", "\n").replace("\r", "\n")
    return cleaned.encode("cp1252", errors="replace").decode("cp1252")
