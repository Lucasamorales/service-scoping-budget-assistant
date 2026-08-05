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

.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy app scripts
```

## Layout

```
app/
  core/          keys, domain types, errors
  knowledge/     manifest, catalog parser, chunking, index, retrieval
  orchestrator/  router, scope resolver, context pack, LLM
  tools/         quoting, budget tracker, mail proposals
  store/         Firestore, Sheets, mailer clients
scripts/         offline tooling; none of it runs inside the deployed service
documents/       the corpus, plus manifest.json declaring each file's type
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

### Tests: invariants versus anchors

[`tests/test_catalog_parsing.py`](tests/test_catalog_parsing.py) holds **invariants** that are
true for any corpus in this format. If one breaks, the code is wrong.

[`tests/test_corpus_anchors.py`](tests/test_corpus_anchors.py) holds **anchors** — facts about
the corpus as it stands, each verified by reading the source. When the service breakdown changes
these will break, and that is correct. Re-verify against the new documents and update the number.
Do not delete the assertion.

## Current state

Working: the service catalog. All 81 documents parse into a typed registry with zero errors,
385 searchable phrases, and full test coverage of the parser.

The validator currently reports 12 warnings, all genuine and none blocking:

- Four documents have trailing whitespace in the status field. Parsed correctly, worth tidying.
- One filename is truncated
  (`...on-site-pla.md` should be `...on-site-placements.md`). The item id comes from the
  `Section` and `Item` fields inside the document, so nothing is broken by this.
- Seven phrases legitimately match more than one item. `video post production` matches three
  items across two sections, and `billboards` matches both Billboards and Hoarding. These are
  real domain overlaps and the resolver disambiguates by asking, which is exactly why a
  similarity score is not allowed to choose the verdict.

Not built yet: chunking and the index, the router and scope resolver, the LLM orchestrator, the
budget tracker, the quoting engine, mail, and the chat widget.

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
