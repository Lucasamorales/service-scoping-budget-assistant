"""Take the README's screenshots from a running assistant.

Drives the real widget against a local server rather than mocking it, so a
picture in the README cannot drift from what the thing actually does: if a
state stops being reachable, this script stops being able to photograph it.

Run the service first, then::

    .\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000
    .\\.venv\\Scripts\\python.exe -m scripts.capture_screenshots

Needs Playwright driving the Chrome already on the machine::

    .\\.venv\\Scripts\\python.exe -m pip install playwright

Not part of the test suite or the deployed image. It is a documentation tool,
and it is checked in so the next person can retake the set instead of guessing
which window sizes and questions produced it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

OUT = Path("docs/images")

# Wide enough for the conversation and the service list side by side, which is
# the layout worth showing; the drawer fallback gets its own narrow shot. CHAT
# is deliberately tighter than WIDE — with the list closed the widget caps at
# 760px, and a wider frame is just navy either side of it.
CHAT = (940, 720)
WIDE = (1180, 760)
NARROW = (460, 860)

TURN_TIMEOUT_MS = 90_000


def _widget(page: Any) -> Any:
    return page.locator("acme-chat")


def _settle(page: Any) -> None:
    """Wait for a turn to finish: the send button re-enables when it does."""
    page.wait_for_function(
        """() => {
            const r = document.querySelector('acme-chat')?.shadowRoot;
            const send = r?.querySelector('button.send');
            return send && !send.disabled;
        }""",
        timeout=TURN_TIMEOUT_MS,
    )


def _ask(page: Any, message: str) -> None:
    field = _widget(page).locator("textarea")
    field.fill(message)
    _widget(page).locator("button.send").click()
    _settle(page)


def _shot(page: Any, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path))
    print(f"  {path}  ({path.stat().st_size // 1024}KB)")


def capture(base: str) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as play:
        browser = play.chromium.launch(channel="chrome")
        context = browser.new_context(viewport={"width": CHAT[0], "height": CHAT[1]},
                                      device_scale_factor=2)
        page = context.new_page()

        print("empty state")
        page.goto(base, wait_until="networkidle")
        page.wait_for_timeout(700)
        _shot(page, "01-start")

        print("a verdict")
        _ask(page, "can we put an advert on a billboard in Basingstoke")
        page.wait_for_timeout(400)
        _shot(page, "02-verdict")

        print("the context box")
        _widget(page).locator(".candidates.actions button").first.click()
        page.wait_for_timeout(400)
        _widget(page).locator(".note-input").fill(
            "Local radio falls through without outdoor support. The site is booked for the "
            "two weeks either side of the reopening and artwork is due on the 26th."
        )
        page.wait_for_timeout(300)
        _shot(page, "03-context")
        page.keyboard.press("Escape")
        _settle(page)

        print("the service list, searched")
        page.set_viewport_size({"width": WIDE[0], "height": WIDE[1]})
        page.goto(base, wait_until="networkidle")
        page.wait_for_timeout(600)
        _ask(page, "can we order some merch")
        _widget(page).locator("[data-open-catalog]:not([hidden])").first.click()
        page.wait_for_selector("acme-chat >> .catalog-group", timeout=20_000)
        _widget(page).locator(".catalog-search-toggle").click()
        _widget(page).locator(".catalog-search-input").fill("video")
        page.wait_for_timeout(400)
        _shot(page, "04-search")

        print("the narrow layout")
        page.set_viewport_size({"width": NARROW[0], "height": NARROW[1]})
        page.wait_for_timeout(500)
        _shot(page, "05-narrow")

        print("the request email")
        page.set_viewport_size({"width": 760, "height": 1180})
        page.goto((OUT / "email.html").resolve().as_uri(), wait_until="networkidle")
        page.wait_for_timeout(700)
        page.screenshot(path=str(OUT / "06-email.png"), full_page=True)
        print(f"  {OUT / '06-email.png'}")

        browser.close()

    # Scaffolding for the browser, not an artefact. The PDF beside it stays:
    # a picture of an attachment is not the same as being able to open one.
    (OUT / "email.html").unlink(missing_ok=True)


# The conversation the sample email reports on. Written out rather than taken
# from a live chat so the picture is stable between runs — a screenshot whose
# content changes every time is a screenshot nobody trusts.
SAMPLE_TURNS = [
    ("14:58", "user", "can we put an advert on a billboard in Basingstoke", None),
    (
        "14:58",
        "assistant",
        "This falls outside of the approved scope, and it's usually priced at £350. "
        "If you'd like to go ahead with it, you'll need a PO approved from your country "
        "manager. I can email your Country Manager to kick things off.",
        "quote_required",
    ),
    ("15:01", "user", "what's left in our budget this month?", None),
    (
        "15:01",
        "assistant",
        "Acme Basingstoke has £1,240 left of a £2,000 cap for August. "
        "A £350 billboard would leave £890.",
        None,
    ),
    ("15:02", "user", "yes please, request the PO", None),
]

CONVERSATION_ID = "8f21c0a4-4d1e-4c77-9a02-6b3ee0b2f1aa"


def _sample_audit(directory: Path) -> object:
    """An audit log holding SAMPLE_TURNS, which is where the PDF reads from."""
    from app.store.audit import AuditEvent, JsonlAuditStore

    store = JsonlAuditStore(directory)
    pending: dict[str, object] = {}
    for time, role, content, verdict in SAMPLE_TURNS:
        at = f"2026-08-20T{time}:00+00:00"
        if role == "user":
            pending = {"at": at, "user_message": content}
            continue
        store.append(
            AuditEvent(
                conversation_id=CONVERSATION_ID,
                kind="turn",
                at=str(pending.get("at") or at),
                payload={
                    "user_message": pending.get("user_message", ""),
                    "assistant_message": content,
                    "status": verdict,
                },
            )
        )
        pending = {}
    return store


def render_email() -> None:
    """Write the HTML the mailer would send, so the browser can photograph it."""
    import tempfile

    from app.core.config import get_settings
    from app.knowledge.catalog import load_catalog
    from app.knowledge.manifest import Manifest
    from app.store.contacts import Contact
    from app.tools.mail import build_request_email

    catalog = load_catalog(Manifest.load(get_settings().documents_dir)).catalog
    scratch = Path(tempfile.mkdtemp(prefix="acme-shots-"))
    draft = build_request_email(
        kind="email_cm_po",
        contact=Contact(
            name="Charlie",
            email="charlie@example.com",
            role="country_manager",
            countries=("United Kingdom",),
        ),
        item=catalog.get("photography--billboards"),
        requester="Robin Morrison",
        role="am",
        country="United Kingdom",
        branch="Acme Basingstoke",
        quote_amount=350.0,
        currency="GBP",
        note=(
            "Local radio falls through without outdoor support. The site is booked for the "
            "two weeks either side of the reopening and artwork is due on the 26th."
        ),
        conversation_id=CONVERSATION_ID,
        audit_log=_sample_audit(scratch),  # type: ignore[arg-type]
        current_message="yes please, request the PO",
        asset_base_url="https://your-service-url.a.run.app",
        from_address="Acme Scoping Assistant <requests@example.org>",
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "email.html").write_text(draft.html, encoding="utf-8")
    (OUT / "conversation.pdf").write_bytes(draft.attachments[0].content)


def render_pdf_page() -> None:
    """First page of the attachment, as a picture."""
    import pypdfium2

    document = pypdfium2.PdfDocument(OUT / "conversation.pdf")
    document[0].render(scale=2).to_pil().save(OUT / "07-pdf.png")
    print(f"  {OUT / '07-pdf.png'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8000")
    args = parser.parse_args(argv)
    try:
        render_email()
        capture(args.base)
        render_pdf_page()
    except ImportError:
        print("Playwright is not installed. See this module's docstring.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
