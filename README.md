# Acme Scoping Assistant and Budget Tracker

> **Placeholders:** "Acme" is an example client and its branches, people, contacts, budgets and rate
> card are sample data. The logo is a placeholder and the fonts are Inter (SIL Open Font License).
> Replace the documents in `documents/`, the workbook and the fixtures with your own before use.

A decision-support assistant for Acme marketing requests across 13 branches in 4 countries.
It answers whether a requested service is in scope, refused, handled locally, or needs a quote,
checks the branch's remaining budget, and drafts the follow-up email for a human to approve.

Somebody at a venue asks in their own words. They get a verdict, the price if there is one, and
a way to send the request onward — in one turn, without reading a scope document.

## What it looks like

The screenshots are not checked in. Take a fresh set from a running instance:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[docs]"   # once, for Playwright
.\.venv\Scripts\python.exe -m scripts.capture_screenshots
```

## The one idea this rests on

Every document in [`documents/`](documents/) carries a `Status code` field with one of four
values. That is the verdict, and it is **read, never inferred**:

| Code | Meaning | Internally |
|---|---|---|
| `Y` | We can do it and is within our scope | `Status.IN_SCOPE` |
| `N` | Can't include as it would require additional resources | `Status.OUT_OF_SCOPE` |
| `Local` | Taken by local or operation teams | `Status.LOCAL` |
| `On demand` | This is something we need to quote | `Status.QUOTE_REQUIRED` |

A language model never picks the verdict. Retrieval supplies the prose that explains it, the
model puts it in the user's language, and a dictionary lookup decides what it is. Three things
follow, and they are the reason the design is worth the extra structure:

- A prompt injection cannot change a verdict, because no user text reaches the lookup.
- Most questions resolve by alias match with no embedding call, saving 100-300 ms.
- "I could not tell which service you mean" is a real answer that routes to a human, instead of
  a confident wrong one.

An unrecognised status code is a **fatal** error, not a defaulted one. The failure it prevents is
an Account Manager being told a chargeable service is free.

## Getting started

Requires Python 3.12 or newer. Developed and tested on 3.14.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,cloud]"
Copy-Item .env.example .env
```

The `cloud` extra pulls in `google-genai` plus Sheets/Firestore clients. For Gemini
wording and embeddings, set `GEMINI_API_KEY` in `.env`
([AI Studio](https://aistudio.google.com/apikey)). **Vertex AI is not used.**
Unit tests and corpus tooling still run offline without the key.

For the architecture decision (why Gemini plans and words but never picks a
verdict), see [`docs/ASSESSMENT-AND-PLAN.md`](docs/ASSESSMENT-AND-PLAN.md).
For integrations and incidents, see [`docs/ASSESSMENT-HANDOFF.md`](docs/ASSESSMENT-HANDOFF.md).
To clone this onto another PC or deploy to Cloud Run, see [`docs/HOSTING.md`](docs/HOSTING.md).

## Commands

```powershell
# Lint the corpus and print what it contains. Run this before trusting anything downstream.
.\.venv\Scripts\python.exe -m scripts.validate_catalog

# Same, but fail on warnings too. Use once the corpus is clean.
.\.venv\Scripts\python.exe -m scripts.validate_catalog --strict

# Refresh documents/manifest.json after adding or removing a document.
.\.venv\Scripts\python.exe -m scripts.generate_manifest

# Raw file statistics: sizes, encoding damage, stray escapes.
.\.venv\Scripts\python.exe -m scripts.report_corpus

# Read the chunks before paying to embed them. No API calls, no writes.
.\.venv\Scripts\python.exe -m scripts.preview_chunks --show 5 --full

# Build artifacts/index.json from the corpus (keyword-only by default).
.\.venv\Scripts\python.exe -m scripts.build_index
.\.venv\Scripts\python.exe -m scripts.build_index --embed   # needs GEMINI_API_KEY

# Score retrieval against evals/retrieval.json. Run before touching a prompt.
.\.venv\Scripts\python.exe -m scripts.eval_retrieval
.\.venv\Scripts\python.exe -m scripts.eval_retrieval --case seo-audit   # show the scoring

# Retake the README's screenshots. Needs the service running and `pip install playwright`.
.\.venv\Scripts\python.exe -m scripts.capture_screenshots

# Score the verdicts the resolver actually produces. Fails only on a wrong verdict.
.\.venv\Scripts\python.exe -m scripts.eval_resolver
.\.venv\Scripts\python.exe -m scripts.eval_resolver --verbose

# Score intent routing. Fails outright if a critical case reaches a lookup.
.\.venv\Scripts\python.exe -m scripts.eval_router

# Score whole turns: right lookup, right service, right verdict, right facts?
# This is the eval that catches "schedule our instagram posts" being answered
# from Marketing calendars — the right tool on the wrong item.
.\.venv\Scripts\python.exe -m scripts.eval_turns
.\.venv\Scripts\python.exe -m scripts.eval_turns --case golden-25-instagram-scheduling --verbose
.\.venv\Scripts\python.exe -m scripts.eval_turns --mode planner    # live Gemini plans, deterministic wording
.\.venv\Scripts\python.exe -m scripts.eval_turns --mode deployed   # what production runs

# Ask the assistant something. Works with no API key and no network.
.\.venv\Scripts\python.exe -m scripts.ask "can we do a billboard for the new branch"
.\.venv\Scripts\python.exe -m scripts.ask "translate our web pages" --trace
.\.venv\Scripts\python.exe -m scripts.ask --prompt "merch"   # what the model is sent
.\.venv\Scripts\python.exe -m scripts.ask                    # interactive, carries context

# Serve the API. Interactive docs at /docs when ENVIRONMENT=local.
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload

.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy app scripts
```

## Layout

```
app/
  main.py        the ASGI app: startup loading, CORS, request logging
  api/           request and response schemas, endpoints
  core/          keys, domain types, errors, settings, logging
  knowledge/     manifest, catalog parser, chunking, index, retrieval
  orchestrator/  plan, execute, compose: planner, executor, facts, guard, wording, resolver, router
  tools/         quoting, budget tracker, mail proposals, catalog list
  store/         Firestore, Sheets, mailer, contacts, roster, quote, audit
scripts/         offline tooling; none of it runs inside the deployed service
widget/          Shadow DOM chat page (TypeScript → dist/acme-chat.js)
documents/       the corpus, plus manifest.json declaring each file's type
prompts/         the always-on instructions, editable without a deployment
evals/           scored cases for retrieval, scoping, routing, and whole turns
tests/           invariants and corpus anchors, kept apart on purpose
docs/            ASSESSMENT-AND-PLAN.md (current architecture) + handoff for review
```

## Working with the corpus

Documents are **declared in `documents/manifest.json`, never discovered by globbing**. A file
missing from disk is an error; a file missing from the manifest is a warning. `docType` drives
chunking and retrieval filtering, and no heuristic reliably tells a service definition from a
glossary from a set of pricing rules, so it has to be author-declared.

After changing any document, run `validate_catalog`. It reports every problem in one pass rather
than stopping at the first, and it distinguishes:

- **Errors** — a verdict cannot be trusted. Fails the build.
- **Warnings** — worth a human reading. Does not block.

## Chunking and retrieval

**A service item is one chunk, never split from its verdict.** The largest document in the corpus
is 2,030 characters, so every one fits whole. A chunk describing what billboards are with no
status attached is not merely incomplete, it invites the model to supply a status of its own. If a
document ever does grow large enough to split, the header naming its section, item and verdict is
repeated on every piece.

Each chunk opens with that header, so a retrieved slice carries its own provenance into the prompt:

```
[Photography — Billboards]
Status: On demand — This is something we need to quote
Use when: outdoor advertising, large format prints, roadside displays, poster ads
```

`Use when` comes from the document's `Also known as` line. It is a retrieval hint written by
someone who knows the domain, and it participates in keyword scoring, which is the cheapest
relevance boost available.

Retrieval is **keyword-first and works with no embeddings at all**. That is deliberate: if it were
useless without vectors, the corpus or the chunking would be wrong. Scoring combines term rarity,
three weight tiers (item name and aliases, then section, then body), rarity-weighted word pairs,
and how much of an item's own name the query accounts for. Two behaviours matter more than the
formula:

- **Force-include beats scoring.** Once the resolver knows which service is meant, that chunk goes
  into the pack directly. A job cannot be done without the slice it is about, and a score is a
  hope rather than a guarantee.
- **Every result explains itself.** Results carry a mode string and the terms that matched, which
  is usually what tells you an answer was wrong before you open a log.

### Embeddings

[`app/knowledge/embeddings.py`](app/knowledge/embeddings.py) adds dense vectors under one contract
recorded in the index artifact: model and dimensionality must match at build time and query time.
A mismatch disables dense scoring rather than ranking across different spaces, which would look
plausible and be quietly wrong.

Documents use `RETRIEVAL_DOCUMENT`, queries use `RETRIEVAL_QUERY`, and truncated vectors are
unit-normalised after every call. Build with `--embed` once `GEMINI_API_KEY` is set; without it
the assistant keeps answering keyword-only. A failed query embedding
degrades within the same turn — keyword still runs — and a failed *build* embedding refuses to
publish, so a half-embedded index never reaches production.

### Measuring retrieval

[`evals/retrieval.json`](evals/retrieval.json) holds 25 requests phrased the way an Account Manager
would write them, not the way the documents are worded, so a case passes only if paraphrase is
handled. Cases are scored, not asserted, because retrieval quality is a number that moves:

```
decisive cases:  23
  rank 1:        20/23 (87%)
  equal-verdict alternate at rank 1: 3
ambiguous cases: 2  candidate retained: 2/2
in top 5:        25/25 (100%)
```

The eval distinguishes two kinds of near-miss, which is the point of it. Where two items read the
question differently but carry the **same verdict**, either answer is correct. Where they carry
**different verdicts**, ranking must not decide: the case is marked `requiresDisambiguation` and
passes only if the right item is among the candidates for the resolver to offer as a choice.

This started at 56% at rank 1. The gap was almost entirely plural mismatch, documents saying
`leaflets` while users type `leaflet`, which is why `app/core/keys.py` now stems. Reading the eval
output found each cause; none of them were visible in the code.

## How a turn is answered

"How much budget is left at Basingstoke?" and "can you do us a billboard?" need different
sources. The old design let one regex pick **both** the tool and the sentence, before anything
had been looked up. A near-miss did not degrade — it answered the wrong thing fluently.

The path is now **plan → execute → compose**. Gemini may choose which lookups to run and how to
say the result. It never chooses a verdict, a price, or a remaining balance.

```
message
  → safety gates (handover, Yes/No mail)     rules only
  → plan   which lookups this turn needs     Gemini, rules if it fails
  → execute  catalog / Sheet / roster / mail  deterministic
  → compose  word the facts                   Gemini, templates if it fails
  → guard    no invented figures, no flipped  free vs chargeable
```

| Job | Who |
|---|---|
| Injury / legal / press — hand to a person | Rules, before any model call |
| Did they confirm the email? | Rules matching Yes/No against pending state |
| Which lookups? (scope, budget, quote, list, roster, …) | Gemini planner, rule fallback |
| Verdict, price, remaining budget | Catalog + Sheet. Not the model |
| Is the budget figure current? | Re-read from the Sheet every `BUDGET_CACHE_TTL_SECONDS` |
| How to say it | Gemini composer, from the fact pack |
| Catch a bad sentence | Guard, then the deterministic wording |

A question can request several lookups. "Do we have budget for a photoshoot in Basingstoke"
wants a price **and** a ledger; the executor runs both.

Flags in `.env`: `USE_LLM_PLANNER` and `USE_LLM_COMPOSER` (both default on). Either can be
turned off without taking the assistant down. [`evals/turns.json`](evals/turns.json) scores the
whole path — the eval that catches a budget question answered as "I don't have that capability."

The always-on instructions live in [`prompts/system.md`](prompts/system.md). If that file is
unreadable the service refuses to start.

### Safety gates the model does not own

[`app/orchestrator/router.py`](app/orchestrator/router.py) still runs first, and two decisions
never leave it: **handover** and **mail confirmation**. The pattern planner is also the fallback
when Gemini is down or returns junk JSON.

**Order is the load-bearing part.** Handover is checked before everything else, so *"we were
shooting photos when someone got hurt, can we use them"* goes to a person rather than being
answered as a photography question.

### Subjects that must reach a person — please review this list

These are subjects where a plausible machine answer is worse than no answer. **I chose this list;
it is a business policy decision and Acme should confirm or change it.**

| Topic | Triggers on |
|---|---|
| safety | injury, accident, hospital, safety incident |
| legal | lawsuit, solicitor, liability, breach of contract |
| data protection | GDPR, personal data, data breach, right to be forgotten |
| press | journalist, press or media enquiry, statement to the press |
| customer resolution | refund, chargeback, compensation, formal complaint |
| commercial terms | discount, renegotiation, waiving a fee |

Each carries a reason written for the person who asked, not for a log.

The patterns lean specific deliberately. "Complaint" on its own would swallow legitimate questions
about **Review management**, which is a real catalog item handled locally — a bad review is
business as usual, not an escalation.

**Employment matters are refused rather than handed over.** Grievances, disciplinaries,
harassment and dismissal route to `Intent.OUT_OF_REMIT`, which says plainly that the subject is
outside what this tool covers and stops. Handover names the person who owns a subject, and there
is no people directory here to name; implying one would be worse than saying so. What it must
never do is fall through to scoping, which is what used to happen — "a grievance raised against
an instructor" was answered as a question about instructor reviews.

`scripts.eval_router` scores 31 messages and **fails outright whenever a critical message reaches
a lookup**. Refusing via handover or via out-of-remit both count as safe; which one is a product
choice. An ordinary misroute between everyday intents is a different, recoverable class.

### Carrying context without inventing it

A bare follow-up like *"and for Basingstoke?"* inherits the previous subject. Two guards keep that
honest: nothing is carried when there is no history, and a message longer than a few words is
treated as standing on its own even if it opens with "and". Carrying stale context into a fully
formed question is invisible to the user, which makes it worse than ignoring it.

When the resolver has asked a clarifying question, the next message is read as an answer to it —
by number ("1", "the second one") or by name ("the hoarding one"). Two cases deliberately select
nothing: naming something that fits several options, and changing the subject entirely. People walk
away from questions, and answering the abandoned one is worse than dropping it.

"And what about merch?" and "and for Bedford?" are both follow-ups, and only the second lacks a
subject of its own. The message is resolved on its own terms first; the previous subject is
consulted only when that finds nothing.

## The scope resolver

Which service a request is about, and therefore what it costs, is decided by
[`app/orchestrator/resolver.py`](app/orchestrator/resolver.py) — a dictionary lookup that no model
output ever reaches. There are four outcomes, and the middle two carry the design:

| Outcome | Meaning | Verdict available |
|---|---|---|
| `RESOLVED` | One service | yes |
| `AGREED` | Several services that all carry the **same** verdict | yes |
| `AMBIGUOUS` | Several services whose verdicts **differ** | no — must ask |
| `UNKNOWN` | Nothing matched well enough | no — hand to a human |

`AGREED` exists because the user asked about scope, not about taxonomy. "Whether you mean
Billboards or Hoarding, both need a quote" is a better reply than a menu, and the corpus has plenty
of these overlaps. `AMBIGUOUS` is the opposite case: when `ad editing` could mean an in-scope
service or one that needs a quote, the choice changes the answer, so only the user may make it.

Matching runs in descending order of confidence. **Phrase containment** first — the longest name or
alias appearing in the request — which is exact, needs no scoring and no embedding call. Keyword
scoring is the fallback.

Three rules were forced by real failures rather than designed up front:

- **A phrase only settles a request if it is anchored by a rare word.** The Copywriting section
  names its items after the thing being written, so the corpus contains items called simply
  `Emails`, `Web pages` and `Paid ads`. Matching those literally sent "set up emails for people who
  abandon their booking" to the copywriter. Requiring two words did not help, because "web pages"
  is two common words.
- **A runner-up is a real rival when the request named a substantial part of what it is**, measured
  by rarity-weighted coverage — not when it merely scores close. No score margin works here: one
  case needed the leader 27% ahead to be trusted while another was still a coin toss at 34%.
  Coverage separates them because it asks a different question.
- **A single matched word only counts when it is most of the item's identity.** The bare word `one`
  scored **12** and won a confident verdict for an unrelated email item, because scores are
  normalised by query length and a one-word message puts all its weight on whatever rare word it
  contains. Raising the threshold would have rejected legitimate requests like `merch` alongside it.
  The distinction is not how much a query scored but *what it named* — so `merch` resolves and `one`
  does not. Conversational filler and ordinals are stopwords too, but that alone would only have
  postponed the problem until the next filler word.
- **A decided verdict is withdrawn if the request also named a service that disagrees.**
  "Do you handle translating our web pages" used to resolve to **Web pages** (free of charge)
  because those words sit in the sentence, while **Translation & localisation** (local) is what
  they asked. The resolver now asks which one they mean. Place words like a branch name do not
  count as naming a rival service.

### Measuring the resolver

`scripts.eval_resolver` scores the same 25 cases, because what reaches a user is the verdict, not
the document. It grades on danger rather than accuracy:

```
  stated a WRONG verdict:   0/25
  answered well:            22/25 (88%)
  named the exact item:     14/25
  asked or handed over when it could have answered: 3/25
```

**Only a wrong verdict fails the run.** Asking costs a turn; wrong advice about what something
costs is the failure this whole design exists to prevent. The three over-cautious cases are
reported, not gated: tuning them away against 25 handwritten cases would fit the cases rather than
the problem, and real usage is the honest input for that.

Note that for a case whose candidates disagree, stating *any* verdict counts as wrong, including
the expected one — it would mean ranking decided something only the user can decide, and happened
to be right.

## The fact pack, the wording, and the guard

[`app/orchestrator/facts.py`](app/orchestrator/facts.py) is what both answer paths read.
Every lookup writes into a `FactPack` — verdict, quote, budget snapshots, listing, roster,
pending email. The deterministic sentences are assembled there as `fallback_text`. The model
is shown the same object as a briefing and asked to word it, not to judge it.

| Outcome | What the briefing says |
|---|---|
| Resolved | The verdict, in the corpus's wording, and not to be reinterpreted |
| Agreed | All candidates, one shared verdict, and *do not ask the user to choose* |
| Ambiguous | **No verdict.** Ask, listing the options. The composer is skipped so a truncated model list cannot replace the question |
| Unknown | **No verdict.** Say so. Do not guess |
| Handover | Give the reason and stop. The model is not asked to paraphrase it |

[`app/orchestrator/wording.py`](app/orchestrator/wording.py) is the only place a model writes
something a user reads, and it runs **after** every decision. Three outcomes, all answers:

- the model wrote something the facts support, and that is used
- the model failed, returned nothing, or broke a guard → deterministic wording, `Answer.degraded`
- there was no model → deterministic wording, nothing marked, because that is not a fault

[`app/orchestrator/guard.py`](app/orchestrator/guard.py) reads the reply back before anyone sees
it. It looks for the failures that cost money: a **figure nobody looked up**, a **verdict turned
upside down** (saying "free of charge" about something that needs a PO), a claim that an
**email was sent** when none was, and **the right figures about the wrong country** — a budget
answer that names a country the lookup was not about is wrong even when every number in it is
real. Turns that carry a figure or a verdict are generated whole and checked before streaming,
because a guarded answer cannot be un-sent halfway through.

## Answering a turn

[`app/orchestrator/pipeline.py`](app/orchestrator/pipeline.py) runs plan → execute → compose and
returns an `Answer` carrying the text, the verdict, the plan, which lookups actually ran, the
citations, and the `ConversationState` for the next turn. Callers pass that state straight back.

The model is optional on purpose. Correctness never rests on Gemini being up:

- unconfigured, unreachable, rate limited or slow → terser, never wrong
- an empty completion counts as a failure (safety filters and token exhaustion both return one)
- every path is testable with no credentials, which is why the unit suite still runs in a few seconds

A handover never reaches the model at all. That wording is fixed and has been reviewed, and a
model handed an injury to discuss might discuss it.

### Asking it something

```powershell
.\.venv\Scripts\python.exe -m scripts.ask "can we do a billboard for the new branch"
.\.venv\Scripts\python.exe -m scripts.ask "what's left for london" --trace
.\.venv\Scripts\python.exe -m scripts.ask --prompt "merch"   # briefing the composer would see
.\.venv\Scripts\python.exe -m scripts.ask                    # interactive, carries context
```

Same pipeline the deployed service runs. With no Gemini credentials it answers from the catalog:

```
**Merch (Renders and other designs for venue exteriors)** — This is something we need to quote.

PLAN       scope {service_phrase='merch'} via rules
RAN        scope, quote
ROUTE      scoping
RESOLVER   resolved via phrase match on 'Merch': Merch [1.00]
ANSWERED   deterministic
CITED      Merch (required by the resolver)
```

`--trace` is the fastest way to answer "why did it say that?". `PLAN` is who decided the lookups;
`RAN` is what actually produced facts. If those disagree, the turn asked for something it could
not find and should have asked you a question instead of answering.

## The HTTP service

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
# http://127.0.0.1:8000/       internal chat page
# http://127.0.0.1:8000/docs   API docs (local only)
```

Build the widget once (or after changing TypeScript under `widget/src/`):

```powershell
cd widget; npm install; npm run build; cd ..
```

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Liveness plus what is actually working |
| `POST /api/session` | Mint a bearer token (internal MVP password) |
| `POST /api/chat` | The finished answer |
| `POST /api/chat/stream` | The same answer as server-sent events |

The corpus and index load once at startup, so that cost lands during container
start rather than on somebody's first question. Startup is intolerant of exactly one thing — a
corpus that will not parse, since without it there are no verdicts — and tolerant of everything
else.

`/api/health` reports `ok` while running without a model or an index, because the assistant answers
correctly in both cases. Reporting unhealthy would have Cloud Run restart a working service in a
loop, turning a reduced capability into an outage.

### The verdict arrives before the prose

```
event: verdict
data: {"verdict": {"status": "quote_required", "meaning": "This is something we need to quote",
                   "service": "Merch"}, "citations": [...], "awaitingAnswer": false}

event: text
data: {"text": "Merch needs quoting before it "}

event: done
data: {"text": "...", "source": "deterministic", "degraded": false, "truncated": false,
       "state": {...}}
```

Scope is a dictionary lookup, so it is settled before a single token is generated. Sending it first
means the widget renders the badge immediately, and a connection that drops mid-answer has still
delivered the part carrying the consequences. `verdict` is a field rather than something to parse
out of the prose.

`done` always arrives, including after a failure, so a client can rely on it rather than on the
connection closing.

**A fallback is only possible until the first fragment is sent.** After that the bytes are gone, so
a model failing before the first fragment is invisible to the user, while one failing after it is
reported as `truncated` rather than by silently appending a second, different answer.

### State lives on the client

The server holds nothing between turns. `done` and `/api/chat` both return the state for the next
turn, and the client sends it straight back, which is what lets Cloud Run scale horizontally with no
session affinity and no shared store. Firestore-backed history can be added for audit without
changing the contract.

Returned state is **not trusted** on the way back in: item ids are checked against the catalog and
unknown ones dropped. The blast radius is small — the worst a forged id achieves is a verdict the
caller could have asked for directly — but a malformed client cannot produce a confusing answer.

Messages are capped at 2,000 characters and unknown fields are rejected, which bounds prompt cost
and removes the easiest way to bury instructions in padding.

### Security

When `SESSION_TOKEN_SECRET` is set, `/api/chat` requires `Authorization: Bearer <token>`. Tokens
are HMAC-signed claims — subject, role, country, branch, expiry — so budget and mail routing can
use them later without revisiting the widget. `POST /api/session` mints one against
`INTERNAL_ACCESS_PASSWORD`; that is enough for an internal tool and deliberately not enough for a
customer launch (put IAP in front first).

Also enforced on every request: an Origin allowlist when configured, an in-memory rate limit, and
hardening headers (`X-Content-Type-Options`, `frame-ancestors 'none'`, …). Locally, leave the secret
and origin list empty and the interactive docs keep working without a login ceremony.

### Tests: invariants versus anchors

[`tests/test_catalog_parsing.py`](tests/test_catalog_parsing.py) holds **invariants** that are
true for any corpus in this format. If one breaks, the code is wrong.

[`tests/test_corpus_anchors.py`](tests/test_corpus_anchors.py) holds **anchors** — facts about
the corpus as it stands, each verified by reading the source. When the service breakdown changes
these will break, and that is correct. Re-verify against the new documents and update the number.
Do not delete the assertion.

## Current state

**The assistant answers end to end today over HTTP, with or without Gemini.** The turn path is
plan → execute → compose. Catalog, Sheet, roster and mail are deterministic; Gemini may choose
lookups and word the facts; a guard discards a reply that invents a figure or flips a verdict.

[`evals/turns.json`](evals/turns.json) is the product eval (74 cases), and it asserts the
**item and the verdict**, not only which capability ran. That distinction matters more than any
other number here: until 26 Aug 2026 the suite scored 51/51 while a request to schedule Instagram
posts was being answered from *Marketing calendars* — the right tool on the wrong item, which no
capability assertion can see.

On the rules planner it currently scores **70/78 (90%), 0 of 18 critical failures, with 8
recorded known failures**; with the model planner and embeddings, which is what production runs,
**73/78**. Six known failures are what remains of the defects found by the 26 August
golden-question round: each one names the task that will fix it, stays visible in every run, and
does not gate CI — see [`docs/REMEDIATION.md`](docs/REMEDIATION.md). A case that starts passing
is reported so its marker gets removed, which is how the count came down. The other two pass in
production and fail offline by design: the guard that catches them needs embeddings, because on
keyword scores alone the requests it should question and the ones it must not overlap. See
`_check_for_costlier_lookalike` in [`app/orchestrator/resolver.py`](app/orchestrator/resolver.py).

The set includes the phrases that used to fail in production: "what's left for london", "who is
my account manager", "do you handle translating our web pages", "what do I get for free", and
"I need to send an email about an upcoming event" — which used to be called free of charge when
the service it describes needs a quote.

Two assertions exist for requests like that last one, where more than one outcome is acceptable.
`forbidVerdict` names the answer a turn must never give, and `expectCandidate` names the option a
question must include: asking "Emails or Automation?" would satisfy an outcome check while still
hiding the service that costs money.

All 92 documents parse into a typed registry with zero errors — 89 of them service items,
across 12 sections, with 434 searchable phrases. The resolver returns a verdict, a clarifying
question, or a handover. Gemini is wired via
`GEMINI_API_KEY` ([Google AI Studio](https://aistudio.google.com/apikey)). A GCP project is for
Firestore / Sheets / GCS — **not** for the model (no Vertex AI).

**Also live:** read-only Google Sheet (budget, pricing tiers, roster), Firestore audit
dual-write, hybrid retrieval — the deploy script builds the index with `--embed` and ships it in
the image, because Cloud Build has no Gemini key of its own — and the designed request email
with its conversation PDF, described under [The handoff email](#the-handoff-email) below.

**Deployed on Cloud Run.** `.\scripts\deploy_cloud_run.ps1` builds the index, writes the
secrets, and ships the image; see [`docs/HOSTING.md`](docs/HOSTING.md).

The corpus itself is unusually clean: `report_corpus` finds no encoding damage, no stray escapes
and only two non-ASCII characters across 136,000.

### Corpus findings that need a human decision

The validator reports 30 warnings. None block the build, but four would give an Account Manager
the wrong answer and are worth Acme's attention. All four are the same knot of content-planning
names:

| Phrase | Declared alias of | Also the name of | Problem |
|---|---|---|---|
| `content strategy` | Content planning (`local`) | SEO content strategy (`in scope`) | verdicts differ |
| `content planning` | SEO content strategy (`in scope`) | Content planning (`local`) | verdicts differ |
| `content plan` | SEO content strategy (`in scope`) | Content planning (`local`) | verdicts differ |
| `content schedule` | SEO content calendar (`in scope`) | Content scheduling (`local`) | verdicts differ |

Each is a phrase one item claims as an alias while it is also the name of a *different* item with
a *different* verdict. Retrieval obeys the corpus exactly; the corpus is what needs correcting.

Three more are harmless because both items share a verdict, though still worth a look. The
clearest is `SEO audit`, listed as an alias of **SEO/AIO monthly report** while a separate item
called **Regular SEO/AIO audits (every 6 months)** exists. Anyone asking about an audit is
currently pointed at the report.

The remaining warnings are cosmetic or expected:

- Four documents have trailing whitespace in the status field. Parsed correctly, worth tidying.
- One filename is truncated (`...on-site-pla.md` should be `...on-site-placements.md`). The item
  id comes from the `Section` and `Item` fields inside the document, so nothing is broken.
- Seven phrases legitimately match more than one item. `video post production` matches three items
  across two sections. These are real domain overlaps and the resolver disambiguates by asking,
  which is exactly why a similarity score is not allowed to choose the verdict.

## The handoff email

When somebody says yes to "shall I email your Country Manager?", this is what goes out —
pictured under [The handoff](#the-handoff) above.

- **Three variants.** In scope to the Account Manager, a purchase order to the Country Manager,
  and a manual quote to the Account Manager when the rate card has no figure. Only the middle one
  carries money; the third is a request to think rather than to approve, so the requester's own
  words are promoted above the details.
- **HTML and plain text from one set of values.** Several recipients only ever see the text part.
  It is the fallback, not a courtesy, so the two can never say different things.
- **Templates are files.** [`app/assets/templates/`](app/assets/templates/) holds the designed
  HTML and text; substitution is a dictionary lookup over `{{token}}` placeholders with no
  expression syntax anywhere near it, and every value is HTML-escaped on the way in. The
  requester's context is typed into a web form, and that is the one field this matters most for.
- **The system's own vocabulary stays out.** The status row reads `Quote required`, not the
  spreadsheet's `Y` or `On demand`; the requester's role reads `Account Manager`, not the sign-in
  code `am`. Both were shipped once and both read as a machine dump.
- **The conversation travels as a PDF**, laid out to the same design and built from the audit log
  rather than the browser's clipped history. Brand faces are embedded, so `£` and `—` render as
  typed rather than depending on a Latin-1 core font.

Two settings shape it, both in [`.env.example`](.env.example):

| Setting | What it does |
|---|---|
| `PUBLIC_BASE_URL` | Where a mail client fetches the logo and the brand faces. An email has no origin, so both URLs must be absolute. Empty is safe: the mail still goes, without the image and in a system font. The deploy script fills it in from the service itself. |
| `MAIL_REDIRECT_TO` | Sends every request email to one address instead of the AM or CM, for testing the whole path without mail reaching them. A redirected message says so in its subject and at the top of both bodies. Empty in production, and the deploy announces it when set. |

Fonts are a bonus, not a requirement: Gmail and Outlook strip web fonts however they are
declared, so the design keeps its hierarchy in the fallback stack. That is why the money figure
is the largest, heaviest thing on the page rather than the only thing set in the display face.

## The internal chat page

[`widget/`](widget/) is a Shadow DOM custom element (`<acme-chat>`) served at `/`. It streams
answers over SSE, renders the verdict badge as soon as the first event arrives, carries
conversation state in `sessionStorage`, and signs in via `POST /api/session` when auth is enabled.

Styles and markup live inside the shadow root so a host page cannot break the layout. Model text is
HTML-escaped before a tiny markdown subset is applied — never injected raw.

Three things in it are worth knowing about:

- **The service list** (`GET /api/catalog`) sits beside the conversation rather than over it, so
  it can stay open while somebody keeps typing, and it groups by verdict because that is the
  question being asked. Its search reads the summaries as well as the names, and marks matches
  with text nodes rather than by splicing tags into escaped text.
- **The context box** is a modal over the whole widget, not a field under the reply. Inline it
  sat below a wall of text and got scrolled past, and people waited for an email that was still
  waiting on them.
- **An offer expires** when the conversation moves past it. The button that confirms an email
  does not carry what it is agreeing to — the service and the amount live in a sealed token, and
  the server keeps one at a time — so a stale "Yes, request a PO" would raise a purchase order
  for whatever was asked about after it.

### Trying Gemini locally

1. Create an API key at [Google AI Studio](https://aistudio.google.com/apikey)
2. Copy `.env.example` → `.env` and set `GEMINI_API_KEY=...`
3. `.\.venv\Scripts\python.exe -m pip install -e ".[dev,cloud]"`
4. Run the server or `python -m scripts.ask "can we order some merch" --trace` — `ANSWERED`
   should show the model name, not `deterministic`. `PLAN` may show `via gemini-2.5-flash`.

To force the old rule-only path while testing: `USE_LLM_PLANNER=false` and/or
`USE_LLM_COMPOSER=false` in `.env`.

`GCP_PROJECT_ID` is for Firestore / Sheets (and later GCS). Gemini does not use Vertex.

**Built and wired locally:** budget tracker (live Sheet when configured), quoting
(both tier prices and the service→tier map from the Sheet), roster, Resend mail,
Firestore audit.
**Running on Cloud Run**, with the widget embedded through a Webflow page. New machine,
secrets, and GCP steps: [`docs/HOSTING.md`](docs/HOSTING.md).
**Still later:** GCS index download at boot, IAP, and a verified Resend domain — until that
last one exists the sender is the provider's sandbox address, which delivers only to the Resend
account owner.

Architecture write-up: [`docs/ASSESSMENT-AND-PLAN.md`](docs/ASSESSMENT-AND-PLAN.md).
Status board: [`docs/ARCHITECTURE-AUDIT.md`](docs/ARCHITECTURE-AUDIT.md).

## Inputs still needed

Four documents were originally listed as missing. Two of them now live on the Sheet:

| Input | Status |
|---|---|
| Branch list (13 branches, 4 countries) | **Live** — Sheet tab `Branches/countries` |
| Budget caps, spend, fiscal calendar | **Live** — Sheet tabs `Budget caps`, `DB`, `Fiscal_calendar` |
| Directory of AM / CM per country | **Live** — Sheet tab `Roster` (plus `fixtures/contacts/country_ams.json`) |
| Pricing tiers | **Live** — Sheet tabs `Pricing_tiers` (tier→price) and `Scope` (service→tier) |
| Business logic: FOC modifiers, thresholds, routing rules | **Not in corpus** — see below |
| Quoting: confirm merch tier with the business | **Answered** — the `Scope` tab says Tier 3 |

The business logic document is the one that still shapes the conversation. The 89 items give
one flat verdict per item, but a leaflet that already exists and needs resizing is free while the
same leaflet built from scratch is quoted. Those branches, the question that decides between them,
and the thresholds around them all live in that file. It should be parsed at build time rather
than transcribed into Python so that marketing owns pricing behaviour, and so there is only ever
one source of truth for it.

## Reference

[`RAG-ARCHITECTURE-GUIDE.md`](RAG-ARCHITECTURE-GUIDE.md) for infrastructure and deployment
patterns, [`RAG-AND-TOOLING-TEMPLATE.md`](RAG-AND-TOOLING-TEMPLATE.md) for retrieval behaviour,
grounding and tool design. Neither is deployed; both record decisions that exist because
something broke.
