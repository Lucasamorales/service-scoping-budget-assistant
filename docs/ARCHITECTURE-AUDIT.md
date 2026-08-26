# Architecture status (updated 2026-08-20)

Supersedes the 2026-08-19 “embeddings slipped” snapshot where it conflicts.  
Architecture write-up: **[ASSESSMENT-AND-PLAN.md](./ASSESSMENT-AND-PLAN.md)**.  
Integrations pack: **[ASSESSMENT-HANDOFF.md](./ASSESSMENT-HANDOFF.md)**.

## Mental model

Plan → execute → compose. Gemini picks lookups and words facts. Tools pick verdicts and numbers.

```mermaid
flowchart LR
  msg[User message] --> gates[Handover / Yes-No]
  gates --> plan[Planner]
  plan --> exec[Executor: catalog Sheet roster mail]
  exec --> facts[Fact pack]
  facts --> word[Composer]
  word --> guard[Guard]
  guard --> out[Answer]
```

Gemini never chooses in/out of scope or invents prices. Spreadsheet is **read-only**.
Handover and mail confirmation stay rules-only.

## Status board

| Area | Status | Notes |
|---|---|---|
| Catalog / scope verdicts | **Ready** | Lookup from corpus; disagreement asks, does not guess |
| Planner | **Ready** | Gemini structured plan; rule fallback |
| Executor / FactPack | **Ready** | Several lookups per turn |
| Composer + guard | **Ready** | Wording only; invented figures / flipped verdicts discarded |
| Catalog list | **Ready** | Full dump via `list_services`; section and status filters reachable |
| Roster | **Ready** | Sheet `Roster` tab |
| Gemini wording | **Ready** | Developer API key only — **no Vertex** |
| Dense / hybrid RAG | **Ready locally** | `gemini-embedding-001` @ 768; rebuild with `--embed` after corpus changes |
| Budget | **Ready** | Live Google Sheet when `BUDGET_SPREADSHEET_ID` set |
| Quote tiers | **Ready** | Prices from Sheet `Pricing_tiers`; service→tier still JSON |
| Mail | **Ready (test)** | Resend résumé + PDF from audit log; `onboarding@resend.dev` until DNS |
| Contacts | **Temp** | Robin AM / Charlie CM |
| Firestore audit | **Ready** | Dual-write JSONL; planned/satisfied capabilities in the trace |
| Whole-turn eval | **Ready** | `python -m scripts.eval_turns` — 74 cases asserting item and verdict; 64/74 with 10 recorded defects, see [REMEDIATION.md](./REMEDIATION.md) |
| Semantic inventory intent | **Off by default** | Caused identical canned replies; see handoff §10.4 |
| Docker / Cloud Run | **Live** | `acme-scoping` in `us-central1`; see [DEPLOY-STATUS.md](./DEPLOY-STATUS.md) |
| Dense index in production | **Ready** | Built by the deploy script and shipped in the image; takes effect on the next deploy |
| Dense retrieval in the *verdict* path | **Ready** | Resolver embeds the phrase it resolves, on the keyword fallback path only |
| CI | **Ready** | `.github/workflows/ci.yml` on push; nightly runs the deployed configuration |
| IAP | **Missing** | |
| GCS index at boot | **Dropped** | Superseded by shipping the index in the image; dead config removed |

## Live Sheet tabs

`Branches/countries`, `DB`, `Budget caps`, `Fiscal_calendar`, `Roster`, `Pricing_tiers`  
(Ignored: `Dashboard`, `Scope`)

## Local commands

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m scripts.ask "what's left for London?" --trace
.\.venv\Scripts\python.exe -m scripts.eval_turns
.\.venv\Scripts\python.exe -m scripts.smoke_sheets
.\.venv\Scripts\python.exe -m scripts.smoke_firestore
```

## Remaining work

Sequenced in [REMEDIATION.md](./REMEDIATION.md), which supersedes this list for anything
touching retrieval or the resolver.

1. The six root causes from the 26 Aug golden round — REMEDIATION.md phases 1–4
2. Production Resend domain
3. Move service→tier onto the Sheet
4. Confirm merch tier with the business
5. IAP and a custom domain
6. ASSESSMENT-HANDOFF still describes the pre-planner path in places
