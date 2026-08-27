# Backlog

Deferred work and known debt. Keep this honest; do not “fix” items by burying them in drive-by patches.

Active plan: [docs/PLAN-business-flows.md](docs/PLAN-business-flows.md).

## Product (waiting on Acme / later slices)

| ID | Item | Why deferred |
|---|---|---|
| P1 | ~~Production tier↔item and tier↔price tables~~ | **Done.** Both come from the sheet: `Pricing_tiers` for tier→price, `Scope` for service→tier. The numbers were already there; the app was reading a hand-maintained fixture that had drifted |
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
| C2 | One-way Scope→catalog status audit script | Partly covered: loading the rate card now warns when a `Scope` row names a service no document answers to, and `scripts/refresh_rate_card.py --check` fails on drift. Statuses themselves are still uncompared |
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
| O1 | ~~No alerting or uptime check~~ | **Done.** `scripts/setup_monitoring.py` — three uptime checks with content matchers on the health body, four alert policies, two log metrics. Idempotent, so it doubles as the record of what exists |
| O2 | ~~Token usage is never captured~~ | **Done.** Per turn, planning plus wording, in the logs and the audit record. Measured live: ~600 tokens to plan, 2,100–3,700 to word |
| O3 | No latency SLA, and the obvious one is unreachable | Measured live: health 0.25s, chat 2.8–6.0s. P95 < 2s is impossible while a turn calls Gemini twice. Split it: verdict path < 500ms (already met), whole turn P95 < 8s |
| O4 | ~~No re-ranking stage~~ | **Measured 27 Aug, not worth building.** See below |
| O5 | No semantic cache (rejected) | Deliberately not done. Traffic is a handful of AMs, and budget/quote answers are live figures — caching those would serve stale money. Only ever cache scope verdicts, never budget, quote or mail turns |
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

### O1 — what is watched, and what each alert means

Run `python -m scripts.setup_monitoring` to reconcile; `--dry-run` to see without changing.

| Alert | Fires when | Why it matters |
|---|---|---|
| Service answering | `"status":"ok"` missing from the health body | Down, or up but unable to serve. A content match, not just a 200 |
| **Budget sheet readable** | `"budget":true` disappears | Someone unshares the Sheet. The service stays up, returns 200, and silently cannot answer any budget question |
| **Embeddings present** | `"embeddings":true` disappears | A deploy shipped a keyword-only index. Retrieval quietly narrows — exactly what was live and undetected until 27 Aug |
| Model contradicting the facts | more than 5 `wording.guard_violation` in an hour | The composer disagreeing with its own verdict. Users see the deterministic wording so nothing wrong is shown, but a run of these means drift |

`acme_turn_tokens` is recorded but **not** alerted on. A threshold chosen before
there is any data is a guess, and a guessed threshold is how alerting gets muted.
Set one once there is a week of baseline.

Alerts go to a single email notification channel. Uptime checks run every five
minutes from four regions, and need two consecutive failures — one missed probe
from one region is internet weather, and an alert that cries wolf gets ignored.

## Done when cleared

Move rows out of this file into git history / PR notes when shipped; do not leave “done” rows rotting here.
