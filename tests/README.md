# tests

Everything here runs offline: no Gemini key, no Google Sheet, no Firestore, no mail. The budget
comes from the checked-in workbook in `fixtures/`, and where a test needs an outside service it
uses a local stand-in with that service's own call shape.

```bash
python -m scripts.build_index
```

```bash
python -m pytest -q
```

The index has to be built first because `artifacts/` is not committed. The tests are grouped by
what they protect: the catalogue and its parsing, chunking and retrieval, the router, planner and
resolver, the guard on generated replies, the budget and quote stores, the HTTP layer and its
hardening, and the request email with its PDF.

Pytest is one of three checks. The others are the evals in `evals/`, run by the `eval_*`
scripts, which assert the item and the verdict a whole turn lands on; and the widget's own
tests in `widget/test`.
