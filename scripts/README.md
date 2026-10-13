# scripts

Command-line tools, run from the repository root as modules:

```bash
python -m scripts.validate_catalog
```

The catalogue check, the index build and the four `eval_*` harnesses are what CI runs and what
this project means by "verified". They are offline and free. The `smoke_*` scripts,
`setup_monitoring` and `capture_screenshots` need live credentials or a browser and are run by
hand.

| File | What it is |
|---|---|
| `ask.py` | Ask the assistant a question from the terminal |
| `backfill_conversations.py` | Bring existing Firestore conversations up to the readable schema |
| `build_index.py` | Build the knowledge index artifact from the corpus |
| `capture_screenshots.py` | Take the README's screenshots from a running assistant |
| `eval_resolver.py` | Score the scope resolver against the same cases retrieval is scored on |
| `eval_retrieval.py` | Assert what retrieval returns, without generating anything |
| `eval_router.py` | Score the intent router against evals/routing.json |
| `eval_turns.py` | Score whole turns against evals/turns.json |
| `generate_manifest.py` | Create or refresh ``documents/manifest.json`` |
| `preview_chunks.py` | Show what the chunker produces, with no API calls and no writes |
| `probe_intents.py` | Route a matrix of realistic utterances through the pipeline and report where they land |
| `refresh_rate_card.py` | Rewrite the offline rate card from the live spreadsheet |
| `report_corpus.py` | Print raw statistics about the corpus files themselves |
| `setup_monitoring.py` | Create the uptime checks, log metrics and alert policies for the service |
| `smoke_firestore.py` | Smoke-test Firestore audit write + read |
| `smoke_sheets.py` | Smoke-test read-only Sheets access (budget tabs + Pricing tier) |
| `validate_catalog.py` | Lint the service breakdown corpus and print what it actually contains |

`coverage.sh` runs everything CI runs under coverage and writes `coverage/lcov.info`.
