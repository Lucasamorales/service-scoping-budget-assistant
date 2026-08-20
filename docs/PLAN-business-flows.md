# Plan: Business flows (no Form, no DB writes)

Supersedes `PLAN-budget-spend-actions.md`. Spreadsheet/xlsx is **read-only context** for budget. The accounts Google Form is **out of scope** for the RAG. Side effects are chat-confirmed emails.

## Keep

- Phase 0 intent gates (BUDGET / QUOTE / ACTION skip retrieve+LLM until tools run).
- `XlsxBudgetStore` + `answer_budget` (read-only remaining = cap − spent).

## Flows (from business + quote logic docs)

| Status | Steps | CTA |
|---|---|---|
| In scope (Yes) | FOC message + optional budget | Ping Account Manager? → email AM |
| On demand | Tier→price quote + budget; flag if quote > remaining | Email for PO? → email CM (v1: same country AM matrix) |
| Local / No | Advice from docs; stop | none |

Variable tier → abort auto-quote; offer AM email for manual pricing.

## Phases

1. **A** — docs/config cleanup (no Form knobs)
2. **B** — roster + country→AM contacts; session country/role
3. **C** — `pendingAction` + `actions[]` Yes/No
4. **D** — quote engine + fixture rate card
5. **E** — Resend send on Yes
6. **F** — conversation audit log
7. **G** — Events/Video corpus catch-up
8. **H** — live Sheets (Viewer only)

## Rules

- Facts from tools; wording from the model (optional).
- Prices and recipients never invented by Gemini.
- Yes in chat is the only send trigger.
- No Form; no writes to the spend `DB`.
