# Conversation audit — smoke checklist

## Local (JSONL)

1. Set `AUDIT_BACKEND=jsonl` (or leave `auto` with empty `GCP_PROJECT_ID`).
2. Ask a few questions in chat.
3. Open `artifacts/audit/<conversation_id>.jsonl`.
4. Confirm each line has `user_message`, `assistant_message`, `subject`, `outcome`, `at`.

## Firestore (Cloud Run / ADC)

1. Install cloud extras: `pip install -e ".[cloud]"`.
2. Set `GCP_PROJECT_ID`, `FIRESTORE_DATABASE=(default)`, `AUDIT_BACKEND=auto` (or `firestore`).
3. Ensure the runtime SA can create documents in Firestore.
4. Send a chat turn, then open Firebase/GCP Console → Firestore → `conversations` → your id → `turns`.
5. Confirm conversation meta (`subject`, `turn_count`) and turn docs (`outcome`, full messages).
6. Confirm an in-scope **Yes** mail path writes `email_drafted` or `email_sent` with `email.to`.

## Identity

1. Widget login requires a **name** (min 2 chars).
2. Audit rows use that name as `subject`.
