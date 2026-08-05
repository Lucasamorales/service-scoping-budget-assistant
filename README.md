# Acme Scoping Assistant and Budget Tracker

A decision-support assistant for Acme marketing requests across 13 branches in 4 countries.
It answers whether a requested service is in scope, refused, handled locally, or needs a quote,
checks the branch's remaining budget, and drafts the follow-up email for a human to approve.

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

The `cloud` extra is separate so the catalog and retrieval layers stay importable without GCP
credentials. Unit tests and corpus tooling run entirely offline.

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

# Build artifacts/index.json from the corpus.
.\.venv\Scripts\python.exe -m scripts.build_index

# Score retrieval against evals/retrieval.json. Run before touching a prompt.
.\.venv\Scripts\python.exe -m scripts.eval_retrieval
.\.venv\Scripts\python.exe -m scripts.eval_retrieval --case seo-audit   # show the scoring

# Score the verdicts the resolver actually produces. Fails only on a wrong verdict.
.\.venv\Scripts\python.exe -m scripts.eval_resolver
.\.venv\Scripts\python.exe -m scripts.eval_resolver --verbose

# Score intent routing. Fails outright on any missed handover.
.\.venv\Scripts\python.exe -m scripts.eval_router

# Ask the assistant something. Works with no GCP project and no network.
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
  orchestrator/  router, scope resolver, context pack, LLM, composer, pipeline
  tools/         quoting, budget tracker, mail proposals
  store/         Firestore, Sheets, mailer clients
scripts/         offline tooling; none of it runs inside the deployed service
documents/       the corpus, plus manifest.json declaring each file's type
prompts/         the always-on instructions, editable without a deployment
evals/           scored test cases for retrieval, scoping and routing
tests/           invariants and corpus anchors, kept apart on purpose
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

## The intent router

Retrieval is a workflow decision before it is a similarity problem. "How much budget is left at
Basingstoke?" and "can you do us a billboard?" need different sources and different answers, and no
amount of semantic search turns one into the other. So
[`app/orchestrator/router.py`](app/orchestrator/router.py) settles the intent first, by pattern, and
the rest of the pipeline is chosen from it. Patterns rather than a model call, because this
decision gates what the assistant is allowed to do, so user text must not be able to argue with it.

Intents: `handover`, `clarification_reply`, `scoping`, `budget`, `quote`, `action`, `follow_up`,
`capabilities`, `greeting`, `unknown`.

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
| people | grievance, harassment, disciplinary, dismissal |
| commercial terms | discount, renegotiation, waiving a fee |

Each carries a reason written for the person who asked, not for a log.

The patterns lean specific deliberately. "Complaint" on its own would swallow legitimate questions
about **Review management**, which is a real catalog item handled locally — a bad review is
business as usual, not an escalation.

### Carrying context without inventing it

A bare follow-up like *"and for Basingstoke?"* inherits the previous subject. Two guards keep that
honest: nothing is carried when there is no history, and a message longer than a few words is
treated as standing on its own even if it opens with "and". Carrying stale context into a fully
formed question is invisible to the user, which makes it worse than ignoring it.

When the resolver has asked a clarifying question, the next message is read as an answer to it —
by number ("1", "the second one") or by name ("the hoarding one"). Two cases deliberately select
nothing: naming something that fits several options, and changing the subject entirely. People walk
away from questions, and answering the abandoned one is worse than dropping it.

`scripts.eval_router` scores 31 messages and **fails outright on any missed handover**, which is a
different class of failure from an ordinary misroute.

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

## The context pack

[`app/orchestrator/context.py`](app/orchestrator/context.py) turns those decisions into the prompt.
Everything upstream produces facts; this is where they become text without becoming negotiable.

The important piece is the **verdict block**. Rather than dropping the documents in and hoping the
model reads the status correctly, the verdict arrives as a separate statement of what the model is
permitted to say — and when the resolver could not decide, it says so explicitly:

| Outcome | What the block says |
|---|---|
| Resolved | The verdict, in the corpus's wording, and not to be reinterpreted |
| Agreed | All candidates, one shared verdict, and *do not ask the user to choose* |
| Ambiguous | **No verdict.** Ask, listing the options. Do not state or hint at one |
| Unknown | **No verdict.** Say so and offer a handover. Do not guess |
| Handover | Give the reason and stop. Do not comment on the substance |

Leaving the verdict out for the ambiguous case would not be enough — a model shown two documents
will happily infer a status from them. The block has to forbid it.

Two smaller rules: **trimming is never silent** (the pack records what was dropped and the prompt
tells the model to say the answer may be incomplete), and **citations always exist**, including
"no supporting documents were retrieved".

The always-on instructions live in [`prompts/system.md`](prompts/system.md) rather than in code, so
whoever owns how Acme talks to its own staff can edit them without a deployment. If that file is
unreadable the service refuses to start: a model with no instructions is far more dangerous than
one that will not boot.

## Answering a turn

[`app/orchestrator/pipeline.py`](app/orchestrator/pipeline.py) runs the whole sequence — route,
resolve, retrieve, assemble, generate — and returns an `Answer` carrying the text, the verdict, the
citations, which path produced it, and the `ConversationState` for the next turn. Callers pass that
state straight back; nothing has to reassemble it.

### The model is optional, on purpose

The verdict is read from the catalog, so a correct answer can be assembled without a model at all.
[`app/orchestrator/composer.py`](app/orchestrator/composer.py) does exactly that, which makes Gemini
a genuine enhancement — better wording, odd phrasing, conversation — rather than something
correctness rests on.

Three things follow:

- The assistant keeps working when Vertex AI is unconfigured, unreachable, rate limited or slow. It
  gets terser, never wrong. `Answer.degraded` says so, so a quiet outage looks like an outage.
- An empty completion counts as a failure. Safety filters and token exhaustion both return one, and
  a blank reply would look like the assistant had nothing to say.
- Every path is testable with no credentials and no network, which is why the full suite runs in
  about three seconds.

A handover never reaches the model at all. That wording is fixed and has been reviewed, and a model
handed an injury to discuss might discuss it.

### Inherited context is a fallback, never a prefix

"And what about merch?" and "and for Bedford?" are both follow-ups, and only the second lacks a
subject of its own. Prepending the previous service to both meant the first was answered about the
previous service — the user asked about merch and was told about translation. No word count
separates those two messages, so the message is resolved on its own terms first and the previous
subject is consulted only when that finds nothing.

### Asking it something

```powershell
.\.venv\Scripts\python.exe -m scripts.ask "can we do a billboard for the new branch"
.\.venv\Scripts\python.exe -m scripts.ask "translate our web pages" --trace
.\.venv\Scripts\python.exe -m scripts.ask --prompt "merch"   # what the model is sent
.\.venv\Scripts\python.exe -m scripts.ask                    # interactive, carries context
```

Same pipeline the deployed service runs. With no GCP project configured it answers from the catalog,
which needs no API key and no network:

```
**Merch (Renders and other designs for venue exteriors)** — This is something we need to quote.

This can be done, but it needs quoting before it goes ahead.
Submit detailed request and await quote

ROUTE      follow_up on 'and what about merch', carrying copywriting--translation-localisation
RESOLVER   resolved via phrase match on 'Merch': Merch [1.00]
ANSWERED   deterministic
CITED      Merch (required by the resolver); Graphic design for emails & templates for emails
```

`--trace` is the fastest way to answer "why did it say that?".

## The HTTP service

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
# http://127.0.0.1:8000/docs
```

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Liveness plus what is actually working |
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

### Tests: invariants versus anchors

[`tests/test_catalog_parsing.py`](tests/test_catalog_parsing.py) holds **invariants** that are
true for any corpus in this format. If one breaks, the code is wrong.

[`tests/test_corpus_anchors.py`](tests/test_corpus_anchors.py) holds **anchors** — facts about
the corpus as it stands, each verified by reading the source. When the service breakdown changes
these will break, and that is correct. Re-verify against the new documents and update the number.
Do not delete the assertion.

## Current state

**The assistant answers end to end today over HTTP, with no GCP project and no network.** Catalog,
chunking, index, keyword retrieval, intent router, scope resolver, context assembly, the Gemini
adapter, the deterministic composer and the FastAPI service with streaming are all in place, tied
together by `Pipeline` and reachable through either `scripts.ask` or `/api/chat`, including
multi-turn conversation.

All 81 documents parse into a typed registry with zero errors and 385 searchable phrases, chunk
into 81 whole-document slices, and the right item is in the top 5 for every case in the eval. The
resolver returns a verdict, a clarifying question, or a handover, and across the eval set produces
**no wrong verdicts and no missed handovers** — the two failures that would actually reach a user
as bad advice.

Gemini on Vertex AI is wired but unexercised: it activates as soon as `GCP_PROJECT_ID` is set, and
until then every answer comes from the composer.

The corpus itself is unusually clean: `report_corpus` finds no encoding damage, no stray escapes
and only two non-ASCII characters across 136,000.

### Corpus findings that need a human decision

The validator reports 18 warnings. None block the build, but three would give an Account Manager
the wrong answer and are worth Acme's attention:

| Phrase | Declared alias of | Also the name of | Problem |
|---|---|---|---|
| `content strategy` | Content planning (`local`) | SEO content strategy (`in scope`) | verdicts differ |
| `content planning` | SEO content strategy (`in scope`) | Content planning (`local`) | verdicts differ |
| `ad editing` | Video editing for ads (`in scope`) | Video editing ad hoc (`quote required`) | verdicts differ |

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

Not built yet: embeddings, the budget tracker, the quoting engine, mail, session tokens, rate
limiting, and the chat widget. Gemini has not yet been run against a real project.

## Inputs still needed

Four documents referenced by the architecture are not yet in the corpus, and three of them are on
the critical path:

| Input | Needed for |
|---|---|
| Branch glossary (13 branches, 4 countries) | canonical branch keys |
| Business logic: FOC modifiers, thresholds, routing rules | the orchestrator |
| Budget spreadsheet layout and access | the budget tracker |
| Directory of responsible people (AM and Country Manager per branch) | mail routing |
| Quoting rate card | the quoting engine, post-MVP |

The business logic document is the one that shapes the conversation. The 81 documents give one
flat verdict per item, but a leaflet that already exists and needs resizing is free while the same
leaflet built from scratch is quoted. Those branches, the question that decides between them, and
the thresholds around them all live in that file. It is parsed at build time rather than
transcribed into Python so that marketing owns pricing behaviour, and so there is only ever one
source of truth for it.

## Reference

[`RAG-ARCHITECTURE-GUIDE.md`](RAG-ARCHITECTURE-GUIDE.md) for infrastructure and deployment
patterns, [`RAG-AND-TOOLING-TEMPLATE.md`](RAG-AND-TOOLING-TEMPLATE.md) for retrieval behaviour,
grounding and tool design. Neither is deployed; both record decisions that exist because
something broke.
