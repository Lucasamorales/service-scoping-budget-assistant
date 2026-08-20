# Conversation audit — smoke checklist

## Local (JSONL)

1. Set `AUDIT_BACKEND=jsonl` (or leave `auto` with empty `GCP_PROJECT_ID`).
2. Ask a few questions in chat.
3. Open `artifacts/audit/<conversation_id>.jsonl`.
4. Confirm each line has `user_message`, `assistant_message`, `person`, `outcome`, `at`.

## Firestore (Cloud Run / ADC)

1. Install cloud extras: `pip install -e ".[cloud]"`.
2. Set `GCP_PROJECT_ID`, `FIRESTORE_DATABASE=(default)`, `AUDIT_BACKEND=auto` (or `firestore`).
3. Ensure the runtime SA can create documents in Firestore.
4. Send a chat turn, then open Firebase/GCP Console → Firestore → `conversations` → your id → `turns`.
5. Confirm the conversation document has:
   - a readable, sortable id — `<date>-<time>-<person>-<random>`, e.g. `20260820-090000-sam-ab12`
   - `person` (the human) and `person_key` (normalised, for querying)
   - `started_at` and `updated_at` as real Firestore **Timestamps**, not ISO strings
   - `summary` — a one-line "what this conversation was about"
   - `turn_count`, and `emails_sent` / `emails_drafted` counted separately
6. Confirm turn documents are ordered by id and carry `outcome`, `at` (a Timestamp) and the
   full messages.
7. Confirm an in-scope **Yes** mail path writes `email_sent` (or `email_drafted` when no mail
   provider is configured, `email_failed` when the provider rejects it) with `email.to`.

Sorting `conversations` by `started_at` descending in the console is the intended way to find
recent conversations; `person_key` is the field to filter on when looking for one person's history.

## Identity

1. Widget login requires a **name** (min 2 chars).
2. Audit rows record that name as `person`. The turn's `subject` field is the *email* subject
   line — the two were one field once, which made the console ambiguous.
