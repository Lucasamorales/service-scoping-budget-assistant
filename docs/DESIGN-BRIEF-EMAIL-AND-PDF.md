# Design brief: request emails and the conversation PDF

Paste everything below the line into Claude Design as a single prompt. It is
written to be self-contained — a designer with no access to this repository can
work from it.

---

## What you are designing

I need two things designed, as a matched pair:

1. **A transactional HTML email**, in three variants, sent by an internal tool
   called the **Acme Scoping Assistant**.
2. **A PDF** that goes out attached to every one of those emails, containing the
   full chat conversation that produced the request.

Both should look like they came from the same product as the chat interface
they originate in. Right now the email is unstyled plain text and the PDF is
default Helvetica on white — neither looks like anything.

## The product, briefly

Acme runs 13 indoor skydiving branches across 4 countries. Local marketing
people at each venue constantly ask the central marketing team for things —
billboards, photoshoots, merch, translations, event videos. Some of those are
covered by the central team for free, some the venue has to handle locally,
some are out of scope, and some need a quote and a purchase order.

The Scoping Assistant is a chat tool that answers "can we do X" with one of four
verdicts, and then — if the request needs a person — offers to email the right
manager. The email you are designing is that handoff.

## Who reads this email, and what they do with it

Two roles, and the difference matters for the design:

- **Account Manager (AM)** — sits in the central marketing team. Reads the email
  to pick up a piece of work, or to price something the rate card doesn't cover.
- **Country Manager (CM)** — holds the budget. Reads the email to approve
  spending money, and raises a purchase order.

Both are busy, both read on a phone first, and both are being asked to make a
decision in under thirty seconds. **The design's whole job is to make the
decision fast.** Someone should be able to glance at the email on a phone and
know: who is asking, from which venue, for what, how much, and what they are
being asked to do about it.

The PDF is the opposite: it is the receipt. Nobody reads it in the normal case.
It exists so that when a CM wants to know *why* someone is asking for a
billboard, the full conversation is one tap away and legible.

## The three variants

Every email carries the same fields. Only the ask changes, and it should be the
most visually prominent thing after the service name.

| Variant | Goes to | Subject line today | The ask |
| :-- | :-- | :-- | :-- |
| `email_am` | Account Manager | `Acme request: {service}` | "Please pick this up as an in-scope (free of charge) request." |
| `email_cm_po` | Country Manager | `PO request: {service}` | "Please raise a purchase order for the amount below." |
| `email_am_variable` | Account Manager | `Manual quote needed: {service}` | "Please price this by hand — it is not on the standard rate card." |

The middle one is the only one carrying a money figure. The third one is the
only one where the reader has to read the requester's context carefully rather
than just approve — it is a request to *think*, not to *tick*.

Feel free to rewrite the subject lines and the ask sentences. They were written
to be functional, not good.

## Exactly what data is available

Every field below is real and already computed. Nothing here needs to be
invented, and please don't design in a field that isn't on this list — if you
want one, say so and I'll tell you whether we can get it.

- **Recipient name** — "Charlie"
- **Requester name** and **their job title** — "Robin Morrison", "Marketing Executive"
- **Country** — "United Kingdom"
- **Branch / venue** — "Acme Basingstoke"
- **Service** — "Billboards (Photography)". The part in brackets is the category
  it sits under in our service catalogue.
- **Status** — a raw code plus its meaning: `On demand` / "This is something we
  need to quote". The four possible verdicts are **In scope**, **Local**,
  **Out of scope**, **Quote required**.
- **Quoted amount** — `350.00 GBP` today, but see the note below. Only present
  on the PO variant.
- **Context from the requester** — free text, typed by the requester into a
  required pop-up before the email is sent. Typically one to three sentences.
  **This is the only part of the email a human wrote deliberately for the
  reader, and it should be designed as the thing it is.** It can be long-ish;
  it must not break the layout.
- **Reference** — a UUID, `8f21c0a4-4d1e-4c77-9a02-6b3ee0b2f1aa`. Needed for
  support, meaningless to the reader. Should be present and de-emphasised.
- **The attachment** — filename `conversation-8f21c0a4.pdf`.

### Two things to fix while you are in here

- The money is currently printed as `350.00 GBP`. Everywhere else in the product
  it is `£350` — a symbol, no trailing zeros, because trailing zeros make a
  ballpark read as an invoice. Design it as `£350`.
- The PO ask says "for the amount below" and the amount is above it. Please
  reword.

## Here is the email exactly as it goes out today

```
Subject: PO request: Billboards (Photography)

Hi Charlie,

A request came through the Acme Scoping Assistant. Summary:

From: Robin Morrison (Marketing Executive)
Country: United Kingdom
Branch: Acme Basingstoke
Service: Billboards (Photography)
Status: On demand — This is something we need to quote
Quoted amount: 350.00 GBP

Context from the requester:
Local radio deal falls through without outdoor support. Site is booked for
the two weeks either side of the Basingstoke reopening, needs artwork by the
26th.

Please raise a purchase order for the amount below.
Reference: 8f21c0a4-4d1e-4c77-9a02-6b3ee0b2f1aa

The full conversation is attached as a PDF.

— Acme Scoping Assistant
```

That flat list is the problem. Six labelled lines of equal weight, and the two
things that actually decide anything — the money and the ask — are buried in
the middle of them.

## The brand

### Colours — these are the live values from the chat interface

```
Navy (header band, user's own messages)     #232F55
Deep navy (headings, primary text)          #14213B
Body text                                   #2C3D50
Muted text                                  #5A6E85
Faint text (references, timestamps)         #8A9BAD
Acme red (the brand accent — use sparingly) #EE2C2C
Blue accent (links, interactive)            #3B6BA5
Page canvas                                 #E4EBF2
Panel                                       #F4F7FA
Card surface                                #FFFFFF
Alt surface                                 #F0F4F8
Hairline / borders                          #D7E0EA
Fine hairline                               #E8EEF4
```

Status colours, used as small pills in the chat. Reuse these so a status means
the same thing in both places:

```
In scope        text #1F7A4D   fill #E6F5EC   border #A9DCC1
Quote required  text #1D5D8C   fill #E7F1F9   border #A9CFE8
Local           text #A6741A   fill #FBF2E0   border #E4C88A
Out of scope    text #6E5A4E   fill #F2EDE9   border #D8C8BC
```

The interface is light — a pale blue-grey canvas with white cards — with one
navy band across the top carrying the logo. It is not a white slab and it is
not a dark theme. The email should feel like a card lifted off that canvas.

### Type

- **Inter** — the interface face, weights 400 / 500 / 700.
- **Inter Display Black** — the display face, used *only* for the two big
  headings in the chat and for small numbered markers. It is very condensed,
  very heavy, and set in uppercase. Loud. One or two words at a time, never a
  sentence.

I have both as woff2 files and can supply them.

**But assume they will not render in email.** Outlook on Windows will not load
a webfont at all, and several other clients won't either. So design the email
with an explicit fallback stack — `"Inter", "Segoe UI", system-ui, sans-serif`
— and make sure the layout still works when every word is Segoe UI. Don't build
a design whose hierarchy depends on Inter Display arriving. It should be a
bonus where it lands, not a load-bearing element.

The PDF has no such constraint: fonts embed, so both faces will render exactly.

### Logo

The Acme lockup is the word "Acme" in white with a red swoosh through it, sized
to sit in a navy band. I have it as SVG. For email it will need to become a PNG
at 2× and be hosted — please specify the pixel dimensions you want it at.

## Hard constraints for the email

These are not stylistic preferences, they are what will break if ignored:

1. **Table-based layout, inline CSS.** No flexbox, no grid, no `<style>` block
   you rely on, no external stylesheet. Gmail strips most of it.
2. **600px maximum width**, single column, stacking cleanly on mobile.
3. **A plain-text alternative must survive.** We send `text` today; the HTML is
   an addition, not a replacement. Please supply the plain-text version too,
   restructured to match the new hierarchy. Some recipients will only ever see
   that one.
4. **The requester's context is untrusted input.** A person typed it into a web
   form. In the HTML version it has to be HTML-escaped. Note this in the
   handoff so it does not get missed in implementation.
5. **No background images, and nothing where a font is the only carrier of
   meaning** — no custom bullets or icons that depend on a glyph arriving.
6. **Dark mode.** Several clients invert colours on their own. Either design so
   inversion doesn't wreck it, or specify what should happen.
7. **The attachment is the only "call to action" that exists.** There is no
   button that links anywhere — this tool has no web app for managers to log
   into. Do not design a "View request" button; there is nothing for it to open.
   If you think there should be one, say so and I will look at whether we can
   build the destination.

## The PDF

Currently: default Helvetica, one column, black on white, no colour, no logo. It
has a title, five metadata lines, then the conversation as alternating
`You` / `Assistant` blocks with timestamps. A page number and the reference in
the footer.

What it needs:

- The same visual identity as the email — same navy, same red, same faces (these
  will embed properly, so use Inter and Inter Display for real).
- A cover header carrying the logo and the same summary block as the email, so
  the PDF stands on its own if it gets forwarded without the email.
- **Clear visual separation between what the requester said and what the
  assistant said.** These are currently just bold labels and it is hard to scan.
  The chat interface distinguishes them as navy right-aligned bubbles for the
  person and white left-aligned cards for the assistant — worth echoing, but
  bubbles in a document can look childish, so use your judgement.
- The assistant's replies carry a **verdict** and sometimes a **money figure**.
  If those can be surfaced in the transcript the way the status pills work in
  the chat, the document becomes scannable rather than just complete.
- Timestamps present but quiet.
- It must survive being long. Some conversations are two turns; some are twenty.
- Print-safe: it will be printed by at least one country manager, guaranteed.

Please specify margins, type sizes, and the grid in a way an engineer can
implement directly. It is currently built with **fpdf2** in Python, which draws
positioned cells and multi-line text blocks — so a design expressed as
coordinates, sizes and weights is implementable, whereas one that assumes a
browser's layout engine is not. If your design genuinely needs HTML-to-PDF
rendering to work, say so explicitly and explain why, and I will change the
library.

## What I want back

1. The HTML email, all three variants, as working HTML I can drop in — not a
   picture of an email.
2. The matching plain-text version of each.
3. The PDF design: a mockup plus a written spec (fonts, sizes, weights, colours,
   margins, spacing) precise enough to implement in fpdf2.
4. A short note on anything you changed about the wording, and why.

Show me the email in both a wide and a narrow rendering, and show me what it
looks like when the brand fonts fail to load.
