# Backlog

Deferred work and known debt. Keep this honest; do not “fix” items by burying them in drive-by patches.

Active plan: [docs/PLAN-business-flows.md](docs/PLAN-business-flows.md).

## Product (waiting on Acme / later slices)

| ID | Item | Why deferred |
|---|---|---|
| P1 | Production tier↔item and tier↔price tables | Fixture rate card ships; Charlie delivers real numbers |
| P2 | International / high-hierarchy contact bucket | Awaiting Charlie (e.g. Manú-class); v1 does not auto-route |
| P3 | Country Manager ≠ Account Manager split | v1 uses one country AM matrix for both CTAs until clarified |
| P4 | Live Google Sheets on Cloud Run (Viewer) | Needs SA email + sheet share; local xlsx until then |
| P5 | ~~Form field entry-ID map~~ | **Killed** — Form is accounts-only; RAG never opens it |
| P6 | ~~App writes to `DB`~~ | **Killed** — spreadsheet is read-only context |
| P7 | Country-total budget questions | Caps sheet has rollups; chat defaults to branch only |

## Corpus

| ID | Item | Why deferred |
|---|---|---|
| C1 | Richer prose for Events / Video production | **Scaffolded (8 docs)**; deepen Q&A over time |
| C2 | One-way Scope→catalog status audit script | Useful CI check; not required for first flow ship |
| C3 | Glossary as `docType` corpus files | Types exist; content not authored yet |

## Engineering debt (fix when touching the area)

| ID | Item | Notes |
|---|---|---|
| D1 | ~~BUDGET / QUOTE / ACTION still resolve+retrieve+LLM~~ | **Done (Phase 0)** |
| D2 | ~~Session country unused~~ | **Done** — country/role/subject feed contacts + mail |
| D3 | ~~Router loaded with `branches=()`~~ | **Done** |
| D4 | `ConversationState.last_intent` not on `StateModel` | Dead round-trip field |
| D5 | ~~No `actions[]`~~ | **Done** — Yes/No CTAs (no Form) |
| D6 | `Intent.QUOTE` vs `Status.QUOTE_REQUIRED` naming | Document + separate types |
| D7 | ~~`app/tools/` and `app/store/` missing~~ | **Done** |
| D8 | ~~`openpyxl` not in `pyproject.toml`~~ | **Done** |
| D9 | ~~Prompt vs live mail~~ | **Done** — prompt matches chat-confirm send |
| D10 | xlsx also under `documents/` | Fixture is `fixtures/budget/` |
| D11 | Token streaming for model path | Stream currently emits full produced text |

## Operations (production readiness)

Audited 27 Aug 2026 against a standard RAG pre-production checklist. Five practices were already
in place — the eval set, embedding-contract enforcement, strict grounding, backend-supplied
citations, and preferring "I don't know" over a guess. These are the gaps.

| ID | Item | Notes |
|---|---|---|
| O1 | No alerting or uptime check | Nothing watches the service. If it dies, or Gemini starts refusing, nobody learns until someone tries to use it. The signals already exist and are unwatched: every degraded turn sets `degraded` and logs `wording.guard_violation`. Highest value, ~1 hour |
| O2 | Token usage is never captured | `usage_metadata` appears nowhere in the codebase, so "what did last month cost" is unanswerable and a cost spike is undetectable. Prerequisite for the cost half of O1 |
| O3 | No latency SLA, and the obvious one is unreachable | Measured live: health 0.25s, chat 2.8–6.0s. P95 < 2s is impossible while a turn calls Gemini twice. Split it: verdict path < 500ms (already met), whole turn P95 < 8s |
| O4 | ~~No re-ranking stage~~ | **Measured 27 Aug, not worth building.** See below |
| O5 | No semantic cache | Deliberately not done. Traffic is a handful of AMs, and budget/quote answers are live figures — caching those would serve stale money. Only ever cache scope verdicts, never budget, quote or mail turns |
| O6 | No trace id correlating one request across log lines | Structured logging and a per-turn decision trace exist; joining them for one request is manual. Retrieval scores are not logged either, only matched terms |

### O4 — why re-ranking was rejected

A re-ranker can only reorder what retrieval already returned, so its ceiling is "put the expected
item first every time it is present". Measured over the 49 eval cases that name an expected item,
with embeddings on:

| | |
|---|---|
| Expected item at rank 1 | 45/49 (92%) |
| Expected item in the top 5 | **49/49 (100%)** |
| Answers already correct | 45/49 |
| Wrong answers with the expected item **already at rank 1** | **3 of 4** |
| Wrong answers where the expected item is below rank 1 | **1** |

Three of the four wrong answers already rank the correct item first — the ranking is not what is
wrong with them, so reordering changes nothing. The one remaining case (`site-visit`) has its two
candidates within 16% of each other, so swapping them leaves the rival admitted and the turn still
asks rather than answering. **Ceiling: zero to one case in forty-nine**, for an extra model call on
every scoping turn.

An earlier estimate quoted rank-1 at 78%. That figure came from `eval_retrieval`, which runs
keyword-only; production runs hybrid. The dense retrieval work had already collected most of what
a re-ranker would have.

The bottleneck is no longer retrieval. All four remaining failures are in what the resolver does
with a good candidate list, or in corpus naming — see `docs/REMEDIATION.md`.

## Done when cleared

Move rows out of this file into git history / PR notes when shipped; do not leave “done” rows rotting here.
