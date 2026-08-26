# Deploy status — pick this up on another PC

**Date:** 2026-08-24  
**Repo:** https://github.com/your-org/service-scoping-budget-assistant  
**GCP project:** `your-gcp-project`  
**Live URL:** https://your-service-url.a.run.app  
**Health:** https://your-service-url.a.run.app/api/health

This file is the session log. Clone/run details that have not changed still live in [`HOSTING.md`](HOSTING.md).

---

## Headline

**Hosted.** Cloud Run service `acme-scoping` in `us-central1` is Ready. The previous `ContainerImageImportFailed` was cleared by rebuilding **without** the non-ASCII meeting-notes filename. Health reports `ok`, `budget: true`, `mail: true`, `model: gemini-2.5-flash`, `authRequired: true`. Probe services have been deleted.

Log in with `INTERNAL_ACCESS_PASSWORD` from `secrets/cloud-run-password.txt` (or `.env` if you copied it there).

---

## What we did (21–24 Aug 2026)

### Already true before the 24 Aug finish

- App on `main`: plan → execute → compose. Verdicts and prices are lookups, never model output.
- Billing on. Secrets in Secret Manager. Sheet shared with both SAs.
- Image built; Cloud Run refused to **import** it (`sha256:4e62ba62…`). Google hello image worked in the same project.
- Meeting-notes file excluded via `.dockerignore` / `.gcloudignore`. First-run secret create fixed in the deploy script.

### This session (this PC, after `git pull`)

1. `gcloud auth login` (user credentials; ADC file still hits a permission error on `adc.json` — ignore it if `gcloud` itself works).
2. `.env` still had no `SESSION_TOKEN_SECRET` / `INTERNAL_ACCESS_PASSWORD`. Deploy **reused** the password file and **minted a new session secret** (Secret Manager version 3). Put both into `.env` on every machine so the next deploy does not rotate the HMAC and kick people out.
3. `.\scripts\deploy_cloud_run.ps1` → revision `acme-scoping-00004-x5t`, new digest `sha256:63e1570013ab4e751d13efd1a74eb58dc9ba964342921e491215162b1a2528aa` (not the failed import digest).
4. `/api/health` as above. Sheet share already done; `budget: true`.
5. Deleted `acme-scoping-probe` and `acme-scoping-imgtest`.

---

## GCP facts

| Item | Value |
|---|---|
| Project | `your-gcp-project` |
| Project number | `000000000000` |
| Region | `us-central1` |
| Service | `acme-scoping` |
| Revision | `acme-scoping-00004-x5t` |
| Image digest | `sha256:63e1570013ab4e751d13efd1a74eb58dc9ba964342921e491215162b1a2528aa` |
| URLs | `https://your-service-url.a.run.app` and `https://acme-scoping-000000000000.us-central1.run.app` (same service) |
| Runtime SA | `000000000000-compute@developer.gserviceaccount.com` |
| Firestore | `(default)` in **`europe-west2`** (cross-region from the service; latency only) |
| Secret Manager | `acme-session-token-secret`, `acme-internal-access-password`, `acme-gemini-api-key`, `acme-mail-api-key` (currently version 3) |

---

## Secrets that are **not** in git

| What | Where |
|---|---|
| `.env` | Local only |
| Chat password | `secrets/cloud-run-password.txt` and Secret Manager `acme-internal-access-password` |
| Session HMAC | Secret Manager `acme-session-token-secret` **v3** (rotated on this deploy). Copy into `.env` as `SESSION_TOKEN_SECRET` |
| Local Sheets JSON | `secrets/your-gcp-project-sheets.json` — local only. Cloud Run does not use this file. |

Copy `.env` and `secrets/` by hand onto another PC. Never commit them.

To pull the current session secret without rotating it:

```powershell
gcloud secrets versions access latest --secret=acme-session-token-secret --project=your-gcp-project
```

Paste that into `.env` as `SESSION_TOKEN_SECRET=…`. Same for `INTERNAL_ACCESS_PASSWORD` from the password file.

---

## Redeploy

```powershell
gcloud auth login
gcloud config set project your-gcp-project
.\scripts\deploy_cloud_run.ps1
```

Safe to re-run. If `.env` has the two secrets, they will not be regenerated.

---

## Not required yet

- IAP, custom domain
- Production Resend DNS
- Dense embeddings in the image
- CI on push to `main`
- Moving service→tier from JSON onto the Sheet
