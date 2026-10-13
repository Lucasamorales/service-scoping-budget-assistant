# app

The service: a FastAPI app that answers one turn at a time as plan, execute, compose. The
language model may choose which lookups to run and how to word the result; it never decides a
verdict or a figure, and a guard discards a reply that tries to.

## `api/`: the HTTP surface

| File | What it is |
|---|---|
| `middleware.py` | Request hardening that sits in front of every route |
| `pending.py` | Tamper-proof carriage of a pending mail action across turns |
| `rate_limit.py` | In-memory rate limiting |
| `routes.py` | HTTP endpoints |
| `schemas.py` | Request and response bodies |
| `session.py` | Server-issued session tokens |

## `orchestrator/`: one turn, start to finish

| File | What it is |
|---|---|
| `context.py` | The always-on instructions the model is given |
| `executor.py` | Running the lookups a plan asked for |
| `facts.py` | What a turn found out, before anybody decides how to say it |
| `guard.py` | Checking a generated reply against the facts it was given |
| `history.py` | Prior turns carried by the client for wording continuity |
| `intent_semantics.py` | Semantic intent helpers — paraphrase without growing phrase lists |
| `llm.py` | The language model, behind a seam narrow enough to do without |
| `pipeline.py` | One turn, start to finish: plan, execute, compose |
| `plan.py` | What a turn needs looked up, separated from how the answer is worded |
| `planner.py` | Turning a message into a request for lookups |
| `resolver.py` | Deciding which service a request is about, and therefore what it costs |
| `router.py` | Deciding what kind of request this is, before deciding what to look up |
| `wording.py` | Saying the facts out loud |

## `knowledge/`: the service catalogue and retrieval over it

| File | What it is |
|---|---|
| `catalog.py` | Parses the service breakdown corpus into an authoritative registry |
| `chunking.py` | Turning documents into retrievable chunks, one strategy per document type |
| `embeddings.py` | Turning text into vectors, under one contract |
| `index.py` | The knowledge index: a JSON artifact built offline, held in memory at runtime |
| `manifest.py` | The declared inventory of corpus documents |
| `preprocess.py` | Text repair applied before chunking |
| `retriever.py` | Retrieval over the in-memory index |
| `summary.py` | One sentence on what a service is, taken from its own document |

## `tools/`: the lookups a plan can ask for

| File | What it is |
|---|---|
| `actions.py` | Server-driven chat actions (Yes/No CTAs — never Form links) |
| `budget.py` | Budget answers from the ledger — wording-ready facts, no LLM required |
| `catalog.py` | Catalog overview answers — services come from the loaded corpus, not retrieval |
| `email_template.py` | Filling in the designed request-email templates |
| `flows.py` | Status-driven business flows: CTAs, quote enrichment, confirm → mail |
| `mail.py` | Build and send request emails after an explicit Yes in chat |
| `quote.py` | Quoting tool — prices come only from the rate card, never the model |
| `transcript.py` | Conversation transcript for AM/CM email attachments |

## `store/`: everything read from or written to the outside

| File | What it is |
|---|---|
| `audit.py` | Conversation audit log — Firestore when configured, local JSONL otherwise |
| `budget.py` | Budget ledger and caps — local workbook now, Google Sheets later |
| `contacts.py` | Country → Account Manager / Country Manager contact matrix (read-only) |
| `mail.py` | Transactional mail — Resend when configured, otherwise a no-op recorder |
| `quote.py` | What an on-demand service costs: which tier it is, and what that tier is worth |
| `roster.py` | Personnel directory from the Roster tab (read-only) |
| `sheets_client.py` | Read-only Google Sheets client (Viewer share + service account) |

## `core/`: shared types and rules

| File | What it is |
|---|---|
| `config.py` | Runtime settings, read once from the environment |
| `errors.py` | Error types raised while loading and validating the knowledge corpus |
| `keys.py` | Canonical key and normalisation functions |
| `logging.py` | Logging configuration, chosen by environment |
| `money.py` | How a figure about money is written, everywhere it is written |
| `signing.py` | HMAC-SHA256 signing for values the client is allowed to carry |
| `types.py` | Domain types for the service catalog |

## `assets/`

Fonts, the placeholder logo and the email templates used for the request email and its PDF.
