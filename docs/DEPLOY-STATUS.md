# Deploy status — pick this up on another PC

**Date:** 2026-08-24  
**Repo:** https://github.com/your-org/service-scoping-budget-assistant  
**GCP project:** `your-gcp-project`  
**Intended host:** Cloud Run service `acme-scoping` in `us-central1` (not Vercel)

This file is the session log and the remaining checklist. Prefer it over chat history. Clone/run details that have not changed still live in [`HOSTING.md`](HOSTING.md).

---

## Headline

The assistant is finished locally. Billing is on. Secrets and a Docker image exist in GCP. The Sheet is shared with the Cloud Run runtime account. **There is still no public URL** because Cloud Run refuses to import *this* image (`ContainerImageImportFailed`). A Google sample image deploys in the same project and region, so Cloud Run itself works.

The last action that did not finish was a rebuild that excludes a non-ASCII meeting-notes filename from the image. That rebuild needs `gcloud auth login` on the machine that deploys (the previous session’s token expired).

---

## What we did (21–24 Aug 2026)

### Already true before this session

- App on `main`: plan → execute → compose. Verdicts and prices are lookups, never model output.
- `Dockerfile`, `scripts/deploy_cloud_run.ps1`, [`HOSTING.md`](HOSTING.md) shipped in `94f1398`.
- Previous Cloud Run attempt (20 Aug) stopped because billing was not linked (`Cloud billing quota exceeded`).

### This session

1. **Billing linked.**  
   `gcloud billing projects describe your-gcp-project` → `billingAccounts/01DF9D-0E9C58-21A9D8` / `True`.

2. **First `.\scripts\deploy_cloud_run.ps1` died in PowerShell.**  
   `gcloud secrets describe` returns `NOT_FOUND` on a first-ever secret. `$ErrorActionPreference = "Stop"` treated stderr as a crash. **Fixed in the script:** ignore stderr, use `$LASTEXITCODE`.

3. **Second/third deploys got much further.**  
   APIs enabled. Secrets created in Secret Manager. Image built (~134 MB, linux/amd64, Docker v2 gzip layers). Cloud Run service `acme-scoping` created, then stuck on **Container import failed**. The container never started (not a PORT / FastAPI / `.env` bug).

4. **IAM granted**
   - Runtime compute SA: `roles/secretmanager.secretAccessor`, `roles/datastore.user`, `roles/artifactregistry.reader`
   - Cloud Run service agent `service-000000000000@serverless-robot-prod.iam.gserviceaccount.com`: `roles/artifactregistry.reader` on the repo `cloud-run-source-deploy`

5. **Isolated the failure**
   - Probe service `acme-scoping-probe` using `us-docker.pkg.dev/cloudrun/container/hello` → **Ready**, URL `https://acme-scoping-probe-000000000000.us-central1.run.app`
   - Same our image, no secrets (`acme-scoping-imgtest`) → **Container import failed**
   - Conclusion: Cloud Run and the project are fine; **this image** is what import rejects.

6. **Sheet share (done).** Two different accounts:
   | Account | Who uses it |
   |---|---|
   | `sheets-reader@your-gcp-project.iam.gserviceaccount.com` | Local PC (JSON key) |
   | `000000000000-compute@developer.gserviceaccount.com` | Cloud Run (ADC, no JSON key) |

   Keep both as **Viewer** on the live budget Sheet. Do **not** set `GOOGLE_APPLICATION_CREDENTIALS` on Cloud Run.

7. **Meeting notes kept out of the image.**  
   `documents/Meeting started 2026_08_11 12_08 GMT-03_00 – Notes by Gemini (Spanish).md` is a Gemini transcript, listed in `scripts/generate_manifest.py` `_SKIP_FILES`, **not** in `documents/manifest.json`. Cloud Run documents this exact import error for non-UTF-8 / awkward filenames. File stays on disk; `.dockerignore` and `.gcloudignore` now exclude `documents/Meeting started*`.

8. **Deploy script also reuses** `secrets/cloud-run-password.txt` if `.env` has no `INTERNAL_ACCESS_PASSWORD`, so a re-run does not mint a new login password.

9. **Rebuild did not run.** `gcloud` in the agent session hit `Reauthentication failed. cannot prompt during non-interactive execution.` Finish on a PC where you can complete `gcloud auth login`.

---

## GCP facts (do not rediscover)

| Item | Value |
|---|---|
| Project | `your-gcp-project` |
| Project number | `000000000000` |
| Region (script default) | `us-central1` |
| Service | `acme-scoping` |
| Image | `us-central1-docker.pkg.dev/your-gcp-project/cloud-run-source-deploy/acme-scoping:latest` |
| Runtime SA | `000000000000-compute@developer.gserviceaccount.com` |
| Cloud Run service agent | `service-000000000000@serverless-robot-prod.iam.gserviceaccount.com` |
| Firestore | `(default)` in **`europe-west2`** (audit works cross-region; latency only) |
| Secret Manager | `acme-session-token-secret`, `acme-internal-access-password`, `acme-gemini-api-key`, `acme-mail-api-key` |
| Logged-in account used | `robin@example.com` |

Throwaway probe services (delete after a real URL works): `acme-scoping-probe`, `acme-scoping-imgtest`.

---

## Secrets that are **not** in git

Copy these by hand onto the new PC. Never commit them.

| What | Where it lives now |
|---|---|
| `.env` | Local only (Gemini, Sheet id, mail, etc.) |
| Chat password | `secrets/cloud-run-password.txt` (gitignored). Also in Secret Manager `acme-internal-access-password`. Put `INTERNAL_ACCESS_PASSWORD` in `.env` on the new machine so deploys stop rotating it. |
| Session HMAC | Secret Manager `acme-session-token-secret`. Put `SESSION_TOKEN_SECRET` in `.env` too, or every deploy mints a new one and invalidates existing logins. |
| Local Sheets JSON | `secrets/your-gcp-project-sheets.json` — local only. Cloud Run does not use this file. |

---

## Finish the deploy (on the new PC)

Needs: Git, Google Cloud SDK, a browser for `gcloud auth login`. Python/Node only if you also want to run locally.

```powershell
git clone https://github.com/your-org/service-scoping-budget-assistant.git
cd Acme-Rag-Quotizator-
# Copy .env from the other machine (or fill from .env.example).
# Copy secrets/cloud-run-password.txt if you already have one.

gcloud auth login
gcloud config set project your-gcp-project

# Confirm billing still on
gcloud billing projects describe your-gcp-project --format="value(billingAccountName,billingEnabled)"

.\scripts\deploy_cloud_run.ps1
```

The script rebuilds in Cloud Build (widget + keyword index, **without** the meeting-notes file) and replaces the `acme-scoping` revision. A few minutes.

**Success looks like:** a printed `https://acme-scoping-…..run.app` and `gcloud run services describe acme-scoping --region us-central1` showing Ready.

Then:

1. Open the URL. Log in with `INTERNAL_ACCESS_PASSWORD` (`.env` or `secrets/cloud-run-password.txt`).
2. `https://<url>/api/health` — `status` should be `ok`. `budget` should be `true` (Sheet already shared with the compute SA).
3. Ask “what’s left for London?” and “can we order merch”.
4. Delete the probe services:
   ```powershell
   gcloud run services delete acme-scoping-probe --region us-central1 --quiet
   gcloud run services delete acme-scoping-imgtest --region us-central1 --quiet
   ```

If it **still** says `Container import failed` after this rebuild, the filename was not the cause. Next diagnostics (do not guess):

- Confirm the new image digest is **not** `sha256:4e62ba62d80cd70372ce7f6d72328486f2f6f3153013cba94980432e38d054e0` (that was the image that failed import).
- Try the same new image in `europe-west2` (Firestore already lives there).
- Open Cloud Run revision logs and confirm there are still **no application logs** (import, not crash-on-start).

---

## Not required for the first hosted test

- IAP, custom domain
- Production Resend DNS (test from-address is already configured)
- Dense embeddings in the image (`--embed` / GCS index at boot)
- CI on push to `main`
- Moving service→tier from JSON onto the Sheet
- Confirming merch tier with the business

---

## Failures already seen (so you do not re-debug them)

| Symptom | What it actually was |
|---|---|
| `NOT_FOUND: Secret acme-session-token-secret` | First-run PowerShell + `gcloud secrets describe`. Fixed in `deploy_cloud_run.ps1`. |
| `Billing account for project is not found` / quota exceeded | **Solved.** Billing is on. |
| `Container import failed` on `acme-scoping` | Image import, not app startup. Google hello image works in this project. Rebuild without the meeting-notes filename has **not** been proven yet. |
| `Reauthentication failed. cannot prompt…` | `gcloud auth login` in a real terminal, then re-run the script. |
| Sheet already shared with `acme-rag-sheets-reader@…` | That is the **local** SA. Cloud Run needs the **compute** SA as well (now done). |
| ADC “quota project does not match” warning | Cosmetic. Optional: `gcloud auth application-default set-quota-project your-gcp-project`. |
