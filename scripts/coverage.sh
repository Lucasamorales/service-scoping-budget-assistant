#!/usr/bin/env bash
# Runs everything CI runs, under coverage, and writes one LCOV report.
#
#   scripts/coverage.sh
#
# Output: coverage/lcov.info, with paths relative to the repo root: the Python
# service (app/), the command-line harnesses (scripts/) and the widget's
# TypeScript (widget/src).
#
# The harnesses are measured by running them, exactly as CI does: the catalogue
# check, the index build and the four evals. They are the project's own
# definition of "verified" (CLAUDE.md), so a figure that left them out would
# describe a different check from the one that gates a merge.
#
# Offline and free: no Gemini key is used and the budget comes from the
# checked-in fixture.
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p coverage
rm -f .coverage coverage/python.lcov coverage/widget.lcov coverage/lcov.info

export GEMINI_API_KEY="" GCP_PROJECT_ID="" BUDGET_SPREADSHEET_ID="" AUDIT_BACKEND=jsonl

run() { python -m coverage run --append --source=app,scripts -m "$@"; }

run scripts.validate_catalog
run scripts.build_index
run pytest -q
run scripts.eval_router
run scripts.eval_retrieval
run scripts.eval_resolver
run scripts.eval_turns

python -m coverage lcov -o coverage/python.lcov
python -m coverage report | tail -1

(cd widget && { [ -d node_modules ] || npm ci; } && npm run --silent coverage)

# One file, forward slashes, and the widget's paths made relative to the repo
# root rather than to widget/.
{
  cat coverage/python.lcov
  sed -e 's#^SF:src#SF:widget/src#' coverage/widget.lcov
} | tr '\\' '/' > coverage/lcov.info
rm -f coverage/python.lcov coverage/widget.lcov

echo "coverage/lcov.info written: $(grep -c '^SF:' coverage/lcov.info) files"
