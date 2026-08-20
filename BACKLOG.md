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

## Done when cleared

Move rows out of this file into git history / PR notes when shipped; do not leave “done” rows rotting here.
