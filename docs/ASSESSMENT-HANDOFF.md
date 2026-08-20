# Acme Scoping Assistant — Assessment handoff pack

**Audience:** a higher-context / higher-reasoning model (or senior engineer) doing a full product + architecture assessment.  
**Date:** 2026-08-20  
**Repo:** Acme RAG / Scoping Assistant  
**GCP project:** `your-gcp-project`  
**Author context:** the agency build with Robin; multi-day implementation + wiring + regressions.

This document is intentionally dense and self-contained. Prefer it over chatting history.

---

## 1. One-sentence product definition

An **internal decision-support chat** for Acme marketing: given a request, it tells Account Managers / GMs whether central marketing will do it (in scope / local / out of scope / quote required), can show **remaining branch budget** and **tier prices**, can **list catalog services**, and can **email AM/CM after explicit Yes** — without letting a language model invent verdicts or prices.

---

## 2. Core design principle (non-negotiable)

**Verdicts are looked up, never inferred.**

| Corpus `Status` | Internal enum | Meaning |
|---|---|---|
| `Y` | `IN_SCOPE` | Central marketing covers it (FOC) |
| `N` | `OUT_OF_SCOPE` | Central will not take it |
| `Local` | `LOCAL` | Site/ops owns it |
| `On demand` | `QUOTE_REQUIRED` | Doable; needs quote / PO path |

Implications:

- Prompt injection cannot change a verdict (user text never reaches the status lookup as authority).
- Gemini’s job is **wording** (optional), not adjudication.
- Wrong “free vs chargeable” is the highest-cost failure mode.

**Spreadsheet / Google Sheet is read-only.** No Form writes, no spend DB writes from the RAG. Robin’s Form is out of band.

---

## 3. What the system is *not*

It is **not** a free-form RAG chatbot that “thinks” end-to-end.

Typical turn:

```
User message
  → Router (rules / sticky session)           [deterministic]
  → Tools (budget Sheet, quote card, catalog list, mail confirm)
     OR Resolver + Retriever (for scoping)
  → Early deterministic answer (most product paths)
     OR ContextPack + Gemini wording (some scoping turns)
     OR Composer fallback (if model missing/fails)
```

If every answer felt identical in testing, that was a **routing bug**, not “the model looping” — see §10.

---

## 4. Runtime architecture (modules)

| Area | Path | Role |
|---|---|---|
| API | `app/main.py`, `app/api/*` | FastAPI, SSE stream, session tokens, health |
| Pipeline | `app/orchestrator/pipeline.py` | One turn orchestration |
| Router | `app/orchestrator/router.py` | Intent classification (regex + sticky budget) |
| Resolver | `app/orchestrator/resolver.py` | Map utterance → service item(s) + outcome |
| Retriever | `app/knowledge/retriever.py` | Keyword + optional dense hybrid |
| Context | `app/orchestrator/context.py` | Builds LLM pack: system + verdict + evidence + history + question |
| LLM | `app/orchestrator/llm.py` | Gemini Developer API (`GEMINI_API_KEY` only; **no Vertex**) |
| Composer | `app/orchestrator/composer.py` | Deterministic wording fallback |
| Catalog list | `app/tools/catalog.py` | Full inventory dump (not top-k RAG) |
| Budget tool | `app/tools/budget.py` + `app/store/budget.py` | Cap − spend |
| Quote tool | `app/tools/quote.py` + `app/store/quote.py` | Tier → price |
| Flows / mail | `app/tools/flows.py`, `app/store/mail.py` | CTA Yes/No → Resend |
| Contacts | `fixtures/contacts/country_ams.json` | AM/CM recipients |
| Audit | `app/store/audit.py` | Firestore + JSONL dual-write |
| Sheets client | `app/store/sheets_client.py` | Read-only Viewer SA |
| Widget | `widget/` | Shadow DOM chat; carries `state` + `history` |
| System prompt | `prompts/system.md` | Always-on LLM instructions (+ meta docs) |
| Corpus | `documents/` + `manifest.json` | Source of scope truth |

---

## 5. Intent → behaviour map

| Intent | How chosen | Answer source | Uses Gemini? |
|---|---|---|---|
| `HANDOVER` | Keyword topics (safety/legal/etc.) | Fixed reason | No |
| `BUDGET` | Budget regex **or** sticky `active_tool=budget` | Sheets/xlsx tool text | No |
| `CAPABILITIES` | Catalog-list regex (or opt-in semantic) | `list_services()` or short “what I can do” blurb | No |
| `GREETING` | Greeting regex | Composer greeting | No |
| `ACTION` | Yes/No / country after CTA | Mail send/draft / cancel | No |
| `QUOTE` / scoping with on-demand | Quote keywords / resolved on-demand item | Quote + budget facts + CM CTA | Usually no (flow text) |
| `SCOPING` (resolved in/local/out) | Resolver | Flow templates + optional Gemini reword | Optional |
| `UNKNOWN` / weak match | Fallthrough | Composer / ask clarify | Optional |

**Sticky budget:** after a budget turn, follow-ups like “and for Manchester?” stay on the ledger until a clear topic change — state is in widget `sessionStorage` (`acme.state`), not in the LLM.

**History:** prior turns are for Gemini continuity on wording turns only; they must not override this turn’s scope fact.

---

## 6. LLM prompt anatomy (when Gemini runs)

**System instruction:** `prompts/system.md` + meta corpus (e.g. tone of voice).

**User turn (`ContextPack.user_turn()`):**

1. Scope / verdict block (authoritative)
2. Supporting documents (retrieved chunks)
3. Notes (trim warnings, etc.)
4. Recent conversation (history)
5. User question

Inspect locally:

```powershell
.\.venv\Scripts\python.exe -m scripts.ask "can we do merch?" --prompt
.\.venv\Scripts\python.exe -m scripts.ask "what's left for London?" --trace
```

Budget / list / mail / greeting paths **never** build this pack for generation (early return).

---

## 7. Hardcoded vs dynamic cheat sheet

### Hardcoded / deterministic
- Intent regexes and sticky rules
- Handover topic table
- Status meanings / next-step templates in flows + composer
- Catalog list formatting
- “What I can do” capabilities blurb (`composer._CAPABILITIES`)
- Contact matrix JSON (currently the agency test emails)
- Service → tier map in `fixtures/quote/rate_card.json` (tier *prices* overlay from Sheet)

### Dynamic / live
- Gemini wording (if configured and path uses model)
- Dense query embeddings (if index has vectors + API key)
- Budget caps/spend/branches/fiscal from **Google Sheet** (source of truth when `BUDGET_SPREADSHEET_ID` set)
- Tier prices from Sheet tab `Pricing_tiers`
- Roster from Sheet tab `Roster`
- Resend sends
- Firestore audit events

### Explicitly not Vertex AI
Chat + embeddings use **Gemini Developer API** (`GEMINI_API_KEY`).  
`GCP_PROJECT_ID` is for Sheets / Firestore / future GCS — not Vertex.  
`USE_VERTEX_AI` was removed; do not reintroduce.

---

## 8. Integrations status (as of 2026-08-20)

| Integration | Status | Notes |
|---|---|---|
| Gemini chat (`gemini-2.5-flash`) | **Working** | API key |
| Gemini embeddings (`gemini-embedding-001` @ 768) | **Working** | Index rebuilt with `--embed` |
| Hybrid retrieval | **On** when index has vectors | |
| Google Sheet budget | **Working** | SA Viewer; tabs below |
| Pricing tiers from Sheet | **Working** | `Pricing_tiers` → 100/200/350 |
| Service→tier map | **JSON fixture** | Merch → Tier 1 interim |
| Resend | **Working** | From `onboarding@resend.dev` until DNS |
| Contacts | **Temp** | Robin AM / Charlie CM @ example.com |
| Firestore audit | **Working** | Dual-write JSONL; project `your-gcp-project`, DB `(default)`, europe-west2 |
| Semantic inventory router | **OFF by default** | `USE_SEMANTIC_INVENTORY=false` — see §10 |
| Dockerfile / Cloud Run / IAP / GCS index pull | **Not built** | |
| Google Sheets write / Form | **Out of scope** | |

### Live Sheet tab names (source of truth)

| Tab | Used |
|---|---|
| `Branches/countries` | Branch list |
| `DB` | Spend lines |
| `Budget caps` | Monthly caps |
| `Fiscal_calendar` | Fiscal month starts |
| `Roster` | People directory |
| `Pricing_tiers` | Tier → price |
| `Dashboard`, `Scope` | Ignored (UI / duplicate) |

Local xlsx `fixtures/budget/acme_scope_db.xlsx` is **offline fallback only** when no spreadsheet id is set. When id is set, Sheet failure does **not** silently fall back (by design).

Service account: `sheets-reader@your-gcp-project.iam.gserviceaccount.com`  
Roles: Sheets via share Viewer; Firestore `roles/datastore.user`  
Key path (gitignored): `secrets/your-gcp-project-sheets.json`

---

## 9. Conversation audit schema (Firestore)

Collection `conversations/{conversation_id}`:

- `subject`, `role`, `country`, `branch`
- `started_at`, `updated_at`
- `turn_count`, `email_count`

Subcollection `turns/{turn_id}`: full payload (`user_message`, `assistant_message`, `intent`, `outcome`, email meta, sticky budget fields, …).

**Session `role`:** from `POST /api/session` (enum `am` / `gm` / `country` / `admin`), default `am`. Distinct from contact roles (`account_manager` / `country_manager`) used for email routing.

Console: Firestore → project `your-gcp-project` → database `(default)` → `conversations`.

---

## 10. Incidents / lessons (important for assessors)

### 10.1 Dense RAG “missing”
Code existed; artifact built without `--embed`. Fixed by rebuilding with `gemini-embedding-001` (not Vertex-only `text-embedding-005`).

### 10.2 Vertex confusion
Naming/`GCP_PROJECT_ID` wrongly implied Vertex. Removed. Gemini API key only for model/embed.

### 10.3 Service list phrase gap
`"give me a list of services"` missed catalog-list regex → fell into scoping → retrieved “Database clean-up…” → FOC + AM CTA. Regex broadened; **listing must never rely on top-k RAG** (incomplete by definition).

### 10.4 Semantic inventory experiment (regression)
Embedding classifier for inventory paraphrases:

- Sat near budget scores (~0.54 vs threshold 0.55).
- On semantic `CAPABILITIES` without list-regex, pipeline returned **static** `composer._CAPABILITIES` → **same answer every time**.

**Mitigation:** `USE_SEMANTIC_INVENTORY=false` by default; if semantic matches, always `list_services()`; raised thresholds if re-enabled.

**Assessment question for the higher model:** Should inventory intent stay regex-only, move to a small structured LLM classify call, or use safer embedding margins + evals?

### 10.5 Tier 4
Came from meeting notes + old fixture, not live Pricing tab. Removed; only tiers 1/2/3 + Variable. Merch mapped to Tier 1 pending confirmation.

---

## 11. Product flows (business)

| Status | Behaviour |
|---|---|
| In scope | FOC message + optional budget awareness + CTA email AM |
| On demand | Tier price + remaining budget + over-budget flag + CTA email CM for PO |
| Variable tier | Abort auto-quote; CTA email AM for manual price |
| Local / Out | Advice; no mail CTA |
| Budget ask | Remaining = cap − spend for branch/month; sticky follow-ups |
| List services | Full catalog by section (optionally filtered) |

Emails only send after chat **Yes**. Resend must be configured; else draft shown.

---

## 12. Local runbook

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,cloud]"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
# UI: http://127.0.0.1:8000/
# Health: http://127.0.0.1:8000/api/health

.\.venv\Scripts\python.exe -m scripts.ask "what's left for Acme London?" --trace
.\.venv\Scripts\python.exe -m scripts.smoke_sheets
.\.venv\Scripts\python.exe -m scripts.smoke_firestore
```

Critical `.env` knobs: `GEMINI_API_KEY`, `MAIL_*`, `GCP_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS`, `BUDGET_SPREADSHEET_ID`, `AUDIT_BACKEND=auto`, `USE_SEMANTIC_INVENTORY=false`.

---

## 13. Open gaps / next decisions

1. **End-to-end UX QA** after semantic off (budget sticky, quote, list, mail, Firestore).
2. **Resend DNS** / production from-address.
3. **Service→tier** should eventually live on the Sheet (today JSON).
4. **Confirm merch tier** with Charlie (Tier 1 interim).
5. **Deploy:** Dockerfile, Cloud Run, Secret Manager, IAP.
6. **CI:** tests + enforce embedded index artifact.
7. **Intent strategy:** regex vs LLM classify vs embeddings (with eval harness).
8. **Widget session role/country/branch** UX still thin (defaults / optional fields).
9. README historically claimed budget/mail “not built” in places — treat this pack + updated docs as truth.

---

## 14. Suggested assessment prompts for the higher model

Copy any of these:

**A. Architecture fitness**  
“Given §2–§7, is the deterministic-tools + optional-LLM-wording design appropriate for an internal scope/budget assistant with high cost of wrong verdicts? What would you change?”

**B. Intent / UX**  
“Users paraphrase freely. Regex inventory routing and sticky budget work but feel brittle; semantic routing caused identical canned answers (§10.4). Propose a concrete intent layer with failure modes and evals.”

**C. RAG role**  
“Clarify the correct role of hybrid RAG here vs catalog lookup vs tools. Where is retrieval load-bearing, and where is it harmful (e.g. ‘list all services’)?”

**D. Production readiness**  
“Using §8 and §13, produce a go-live checklist for Cloud Run on `your-gcp-project`, including IAM, secrets, Sheet Viewer, Resend, Firestore, and rollback.”

**E. Data model**  
“Review audit schema (§9) and Sheet tabs (§8) for reporting and ops: what’s missing for AM coaching / dispute trails?”

---

## 15. Key file index for deep dives

- Pipeline: `app/orchestrator/pipeline.py`
- Router: `app/orchestrator/router.py`
- Semantic inventory (opt-in): `app/orchestrator/intent_semantics.py`
- System prompt: `prompts/system.md`
- Context pack: `app/orchestrator/context.py`
- Budget Sheets: `app/store/budget.py`, `app/store/sheets_client.py`
- Quote: `app/store/quote.py`, `fixtures/quote/rate_card.json`
- Contacts: `fixtures/contacts/country_ams.json`
- Audit: `app/store/audit.py`
- Business plan: `docs/PLAN-business-flows.md`
- Smoke: `scripts/smoke_sheets.py`, `scripts/smoke_firestore.py`

---

*End of handoff pack. Prefer updating this file when integration status changes rather than relying on chat transcripts.*
