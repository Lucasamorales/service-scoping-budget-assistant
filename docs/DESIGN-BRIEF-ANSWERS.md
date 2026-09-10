# Answers to the design questions

Paste this back. Each answer says what the system actually holds today, since
three of the six options on offer are not buildable as described.

---

## 1. Per-turn verdict in the PDF — **per turn, with pills optional**

Both of your first two options are half right, so here is the actual shape of
the data:

- The audit log **does** store a verdict on every turn. Available now, no work.
- It does **not** store the service name or the amount per turn. Only the
  verdict enum: `in_scope` / `quote_required` / `local` / `out_of_scope`.
- The transcript builder currently ignores it entirely — it reads only the two
  message strings. Wiring the verdict through is small.

The thing that decides your design, though: **many turns legitimately have no
verdict at all.** A budget answer, a clarifying question, a greeting, and the
"which signage did you mean" turns all record nothing, because no service was
resolved. So it is not a case of degrading gracefully in the rare case — a
transcript with pills on some turns and nothing on others is the *normal*
rendering, and it needs to look deliberate rather than broken.

Per-turn amounts I would have to add to the recorded payload. That is a
one-line change, but it only applies going forward — conversations already in
the log would have none. So don't design a layout that needs the amount on
every turn.

One verdict on the cover as well is worth having regardless: that is the
request being approved, and it is the one a reader wants without scrolling.

## 2. mailto back to the requester — **no links at all**

Not a preference. **We do not have the requester's email address**, anywhere in
the system.

Sign-in is a single shared password plus a name, role, country and branch the
person types about themselves. There are no per-person accounts, no email
field, and no verified identity. The "From: Robin Morrison" on the email is
free text somebody typed into a box.

So there is nothing to put in a `mailto:`, and nothing to put in a `Reply-To`
either. Even if we added a field tomorrow it would be self-declared and
unverified — a reply link pointing wherever the requester chose to type.

Making reply-to-requester real means per-user accounts or SSO. That is an
authentication change, not a design decision. Design it with no links; if the
business wants a reply path, tell me and I will scope the auth work separately.

## 3. How the HTML should arrive — **plain HTML with `{{field}}` tokens**

There is no template engine in the project today, so nothing is locked in and
that option keeps it that way — I can render it with whatever I choose, and
adding Jinja2 later is one dependency line.

Please avoid the f-string / `.format` option specifically: the HTML will be
full of inline CSS, and **every `{` and `}` in a style attribute collides with
Python's format syntax.** It would have to be escaped by doubling every brace
in the file, which makes the template unreadable and unmaintainable.

`{{field}}` tokens have no such collision. Use exactly that spelling, double
braces, and list the token names you have used at the top of the file.

## 4. The in-chat context pop-up — **yes, include it**

Worth knowing before you start: **it already exists and is live.** You are
redesigning something, not designing it. Screenshot attached.

What it does today, all of which should survive:

- It is a modal over the whole widget with the conversation blurred behind, not
  a field under the reply. Inline it sat below a wall of text and got scrolled
  past, and people waited for an email that was still waiting on them.
- **Send it** stays disabled until something is typed. The requirement is
  enforced on the server too — this is just the fast half, so nobody makes a
  round trip to be told the box was empty.
- Enter sends, Shift+Enter breaks the line.
- Escape cancels, and cancelling declines the email rather than silently
  dropping it.
- Focus is trapped inside the dialog.
- 1000 character limit.

The prompt text changes by variant. For a manual quote it reads "Add some
context — what do they need to know to price it?" rather than the generic one,
because that is the case where the reader has to act on the detail.

## 5. Timestamps — **UTC, labelled**

Venue local time is not available. There is no timezone data for the branches
anywhere in the system, and country would not be enough to derive it — two of
the four countries are Canada and Australia, which each span several zones.

Everything is stored as UTC. A dated header with times underneath is welcome if
it reads better on a long transcript, as long as the zone is stated once
somewhere visible.

Note a bug while you are here: the transcript currently prints `2026-08-20
16:01` with no zone marker at all, which reads as the reader's local time and
is not. Whatever you choose, the label has to be on it.

## 6. The footer

Three things belong there:

- **The reference** — the conversation id. It already exists in the body; the
  footer is where it should live.
- **An internal-tool disclaimer.** Say plainly that the mail was sent
  automatically, that the verdict comes from the marketing scope documentation
  and the price from the rate card. A manager who thinks a person wrote this
  will reply to it, and nobody is reading that mailbox.
- **The from-address as a token, never hardcoded.** Right now it is
  `Acme Scoping <onboarding@resend.dev>` — the mail provider's *sandbox*
  domain, which only delivers to the account owner. It has to change to a real
  Acme domain before anyone else can receive these at all. Leave it as a field.

A support contact I cannot give you — we do not have one. That is a question
for the business, and I will chase it.

Given the reply problem in question 2, the footer is also the honest place to
say replies are not monitored. If Acme would rather set up a real monitored
inbox, that changes the answer — flag it and I will ask.
