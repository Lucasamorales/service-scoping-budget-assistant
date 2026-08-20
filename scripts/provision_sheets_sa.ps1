# Provision a Viewer-only service account for Google Sheets on your-gcp-project.
# Run in an interactive PowerShell (gcloud must be able to open a browser login).
#
# Usage:
#   .\scripts\provision_sheets_sa.ps1
#   .\scripts\provision_sheets_sa.ps1 -ProjectId your-gcp-project
#
# Afterward:
#   1. Share the live spreadsheet with the printed SA email as Viewer
#   2. Set BUDGET_SPREADSHEET_ID and GOOGLE_APPLICATION_CREDENTIALS in .env

param(
    [string]$ProjectId = "your-gcp-project",
    [string]$SaName = "acme-rag-sheets-reader",
    [string]$KeyOut = "secrets/your-gcp-project-sheets.json"
)

$ErrorActionPreference = "Stop"

Write-Host "Project: $ProjectId"
Write-Host "Re-auth if needed: gcloud auth login"
gcloud config set project $ProjectId

Write-Host "Enabling Sheets API..."
gcloud services enable sheets.googleapis.com --project $ProjectId

$SaEmail = "$SaName@$ProjectId.iam.gserviceaccount.com"
$exists = gcloud iam service-accounts describe $SaEmail --project $ProjectId 2>$null
if (-not $exists) {
    Write-Host "Creating service account $SaEmail ..."
    gcloud iam service-accounts create $SaName `
        --project $ProjectId `
        --display-name "Acme RAG Sheets reader (read-only)"
} else {
    Write-Host "Service account already exists: $SaEmail"
}

$dir = Split-Path -Parent $KeyOut
if ($dir -and -not (Test-Path $dir)) {
    New-Item -ItemType Directory -Path $dir | Out-Null
}

Write-Host "Writing key to $KeyOut (do not commit)..."
gcloud iam service-accounts keys create $KeyOut `
    --iam-account $SaEmail `
    --project $ProjectId

Write-Host ""
Write-Host "Done."
Write-Host "1) Share your Google Sheet with this email as Viewer:"
Write-Host "   $SaEmail"
Write-Host "2) Put in .env:"
Write-Host "   GCP_PROJECT_ID=$ProjectId"
Write-Host "   GOOGLE_APPLICATION_CREDENTIALS=$KeyOut"
Write-Host "   BUDGET_SPREADSHEET_ID=<id from the sheet URL>"
Write-Host "3) Smoke test:"
Write-Host "   .\.venv\Scripts\python.exe -m scripts.smoke_sheets"
