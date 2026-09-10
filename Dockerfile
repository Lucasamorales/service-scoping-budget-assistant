# Cloud Run image: widget bundle + knowledge index + FastAPI.
#
# The catalog and index are baked in at build time so a cold start does not
# rebuild them, and so a missing local artifacts/ folder cannot ship an empty
# knowledge base.
#
# The index normally arrives already built, with embeddings, from
# scripts/deploy_cloud_run.ps1 — Cloud Build has no Gemini key, and shipping a
# keyword-only index while every local check ran against vectors is how the
# deployed service ended up quietly weaker than the one being tested. Building
# it here is the fallback for `docker build` by hand, and produces the
# keyword-only index that mode has always produced.

FROM node:22-bookworm-slim AS widget
WORKDIR /src/widget
COPY widget/package.json widget/package-lock.json ./
RUN npm ci
COPY widget/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY scripts ./scripts
COPY documents ./documents
COPY fixtures ./fixtures
COPY prompts ./prompts

# The bracket makes the source optional: with a shipped index it is copied, and
# without one COPY matches nothing instead of failing the build.
COPY artifacts/index.jso[n] ./artifacts/

RUN pip install --no-cache-dir ".[cloud]" \
    && if [ -f artifacts/index.json ]; then \
         echo "Using the index shipped with this build."; \
       else \
         echo "No index in the build context; building keyword-only."; \
         mkdir -p artifacts && python -m scripts.build_index --out artifacts/index.json; \
       fi

COPY --from=widget /src/widget/dist ./widget/dist
COPY widget/index.html ./widget/index.html
# Brand faces, served from this origin rather than a font CDN.
COPY widget/assets ./widget/assets

EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
