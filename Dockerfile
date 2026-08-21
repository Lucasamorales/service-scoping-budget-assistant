# Cloud Run image: widget bundle + keyword index + FastAPI.
#
# The catalog and index are baked in at build time so a cold start does not
# rebuild them, and so a missing local artifacts/ folder cannot ship an empty
# knowledge base. Embeddings are left off the image on purpose — they need a
# Gemini key at build time, and keyword retrieval is a supported mode.

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

RUN pip install --no-cache-dir ".[cloud]" \
    && mkdir -p artifacts \
    && python -m scripts.build_index --out artifacts/index.json

COPY --from=widget /src/widget/dist ./widget/dist
COPY widget/index.html ./widget/index.html

EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
