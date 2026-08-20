"""Smoke-test read-only Sheets access (budget tabs + Pricing tier).

Requires in .env:
  GCP_PROJECT_ID / GOOGLE_APPLICATION_CREDENTIALS / BUDGET_SPREADSHEET_ID
"""

from __future__ import annotations

from app.core.config import get_settings
from app.store.budget import build_budget_store
from app.store.quote import load_quote_store


def main() -> int:
    get_settings.cache_clear()
    settings = get_settings()
    if not settings.budget_spreadsheet_id.strip():
        print("BUDGET_SPREADSHEET_ID is empty — paste the id from the sheet URL.")
        return 1
    if not settings.google_application_credentials.strip():
        print(
            "GOOGLE_APPLICATION_CREDENTIALS is empty — "
            "run scripts/provision_sheets_sa.ps1 first."
        )
        return 1

    print(f"project={settings.gcp_project_id or '(unset)'}")
    print(f"spreadsheet={settings.budget_spreadsheet_id}")
    print(f"credentials={settings.google_application_credentials}")

    budget = build_budget_store(
        xlsx_path=settings.budget_xlsx_path,
        spreadsheet_id=settings.budget_spreadsheet_id,
        credentials_path=settings.google_application_credentials,
    )
    if budget is None:
        print("Budget store failed to load.")
        return 1
    print(f"budget_backend={type(budget).__name__} branches={len(budget.branches())}")
    for branch in budget.branches()[:3]:
        print(f"  - {branch.name} ({branch.country})")

    quote = load_quote_store(
        settings.quote_rate_card_path,
        spreadsheet_id=settings.budget_spreadsheet_id,
        credentials_path=settings.google_application_credentials,
    )
    if quote is None:
        print("Quote store failed to load.")
        return 1
    print(f"quote_tiers={quote.tiers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
