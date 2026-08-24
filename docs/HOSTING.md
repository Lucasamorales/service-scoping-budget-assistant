# Where this project is, how to clone it, how to host it

**Date:** 2026-08-24  
**Repo:** https://github.com/your-org/service-scoping-budget-assistant  
**GCP project:** `your-gcp-project`  
**Intended host:** Cloud Run in `us-central1` (not Vercel)

This is the clone/run book. **Current deploy status and remaining steps:** [`DEPLOY-STATUS.md`](DEPLOY-STATUS.md). Prefer those two files over chat history.

---

## Where we are

The assistant **runs end to end locally**: scope verdicts from the corpus, budget/roster/prices from a Google Sheet, Gemini for planning and wording, a guard that rejects invented figures / flipped verdicts / the wrong country, HMAC-signed mail CTAs, Resend résumé + PDF, Firestore audit.

**Not live on the internet yet.** Billing is linked. Secrets and an image exist in GCP. The live Sheet is shared with the Cloud Run runtime SA. Cloud Run still fails to **import** the app image (`ContainerImageImportFailed`). A Google hello image deploys in the same project, so the next step is rebuilding without the non-ASCII meeting-notes filename and deploying again — see [`DEPLOY-STATUS.md`](DEPLOY-STATUS.md).

| Piece | Status |
|---|---|
| App + tests on `main` | Done |
| GitHub remote `origin`, branch `main` | Pushed |
| `Dockerfile`, `.dockerignore`, `.gcloudignore` | In repo |
| `scripts/deploy_cloud_run.ps1` | In repo (first-run secret create + password reuse) |
| Billing on `your-gcp-project` | **On** |
| Secret Manager + Artifact Registry image | Created |
| Sheet Viewer for Cloud Run compute SA | Done |
| Cloud Run URL | **Blocked on image import** — rebuild pending |
| IAP, custom domain, GCS index at boot | Not started — after the test URL works |

Do **not** host this on Vercel. That was the old Node RAG template. This is a FastAPI process that loads the catalog, index and Sheet at boot and streams SSE. Cloud Run is the host it was written for.

---

## New machine (Windows)

Needs Python 3.12+, Node 20+ (only to rebuild the widget), Git, and optionally Google Cloud SDK.

```powershell
git clone https://github.com/your-org/service-scoping-budget-assistant.git
cd Acme-Rag-Quotizator-

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,cloud]"

Copy-Item .env.example .env
# Fill .env from the list below. Never commit it.

cd widget
npm ci
npm run build
cd ..

.\.venv\Scripts\python.exe -m scripts.build_index
# Optional, needs GEMINI_API_KEY:
# .\.venv\Scripts\python.exe -m scripts.build_index --embed

.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
# http://127.0.0.1:8000/
```

Secrets and keys live only on the machine that already ran this (or in a password manager). They are **not** in git. Copy them by hand:

| Variable | What it is |
|---|---|
| `GEMINI_API_KEY` | [AI Studio](https://aistudio.google.com/apikey). Vertex is not used. |
| `GCP_PROJECT_ID` | `your-gcp-project` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to a Viewer service-account JSON. Create with `.\scripts\provision_sheets_sa.ps1` if you do not have `secrets/your-gcp-project-sheets.json`. **Do not commit the JSON.** |
| `BUDGET_SPREADSHEET_ID` | The id in `https://docs.google.com/spreadsheets/d/<ID>/edit` |
| `MAIL_API_KEY` / `MAIL_FROM_ADDRESS` | Resend. Skip until you want hosted email. |
| `SESSION_TOKEN_SECRET` | Random hex. Required before `/api/session` will mint tokens. |
| `INTERNAL_ACCESS_PASSWORD` | The chat-page password. |

Share the live Sheet as **Viewer** with the service-account email printed by `provision_sheets_sa.ps1`.

Smoke:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m scripts.smoke_sheets
.\.venv\Scripts\python.exe -m scripts.smoke_firestore
```

`gcloud` on a new PC:

```powershell
gcloud auth login
gcloud config set project your-gcp-project
```

---

## Host it on Cloud Run

### 1. Billing (done)

Cloud Run, Artifact Registry, Cloud Build and Secret Manager will not enable on a project with no billing account. This project is already linked. Re-check only if a later deploy says billing is missing.

If you ever need to link it again:

1. Open https://console.cloud.google.com/billing/linkedaccount?project=your-gcp-project
2. Attach a billing account that still has project quota.
3. If the agency is the right account and Google says quota exceeded, request an increase: https://support.google.com/code/contact/billing_quota_increase — then attach it.

Confirm:

```powershell
gcloud billing projects describe your-gcp-project --format="value(billingAccountName,billingEnabled)"
```

`billingEnabled` must be `True` before the next step.

### 2. Deploy

From the repo root, with `.env` filled (the script copies secrets into Secret Manager and does not print them):

```powershell
gcloud auth login
gcloud config set project your-gcp-project
.\scripts\deploy_cloud_run.ps1
```

That builds the image in Cloud Build (widget + keyword index baked in), deploys service `acme-scoping` to **`us-central1`**, min instances 0, allows unauthenticated HTTP, and protects the chat UI with `INTERNAL_ACCESS_PASSWORD`.

If the password was generated rather than taken from `.env`, it is written to `secrets/cloud-run-password.txt` (gitignored).

### 3. After the URL exists

The script prints:

- `https://acme-scoping-…..run.app`
- the Cloud Run runtime service account (`<project-number>-compute@developer.gserviceaccount.com`)

Then:

1. Share the live Sheet as **Viewer** with that runtime SA (this is a different email from the local JSON key). **Already done** for `000000000000-compute@developer.gserviceaccount.com`. Until you do, hosted budget/roster/prices stay empty.
2. Open the URL, sign in with `INTERNAL_ACCESS_PASSWORD`.
3. Hit `/api/health` — `status` should be `ok`. `budget` becomes true after the Sheet share.
4. Ask “what’s left for London?” and “can we order merch”.

Do not set `GOOGLE_APPLICATION_CREDENTIALS` on Cloud Run. The runtime SA is ADC.

### 4. Later (not required for the first hosted test)

- IAP in front of the URL
- Custom domain
- Production Resend DNS
- Rebuild the image with `--embed` (or a GCS index at boot) if you want dense retrieval in production
- CI on push to `main`

---

## If deploy fails again

| Symptom | Cause |
|---|---|
| `Billing account for project is not found` | Step 1 above |
| `Cloud billing quota exceeded` | Request a quota increase, or use another billing account |
| `secretmanager.googleapis.com not enabled` | Same as billing — APIs cannot enable without it |
| Health `ok` but `budget: false` | Sheet not shared with the **Cloud Run** SA |
| Chat has no login / 503 on `/api/session` | `SESSION_TOKEN_SECRET` or `INTERNAL_ACCESS_PASSWORD` missing from Secret Manager |
| Widget is a blank page | Image built without `npm run build` — the Dockerfile already does this; a hand-rolled image might not |
| `Container import failed` | Rebuild without the meeting-notes filename; see [`DEPLOY-STATUS.md`](DEPLOY-STATUS.md) |
| `NOT_FOUND` on `gcloud secrets describe` | First-run PowerShell issue — fixed in `deploy_cloud_run.ps1` |

Re-run `.\scripts\deploy_cloud_run.ps1` after `gcloud auth login`. It is safe to run again: it adds new secret versions and replaces the Cloud Run revision.
