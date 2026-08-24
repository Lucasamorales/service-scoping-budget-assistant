# Deploy the assistant to Cloud Run in us-central1 (fastest generic region).
#
# Usage (from the repo root, gcloud already logged in):
#   .\scripts\deploy_cloud_run.ps1
#
# Reads non-empty values from .env and stores secrets in Secret Manager.
# Does not print secret values. The login password is written to
# secrets/cloud-run-password.txt (gitignored) if it had to be generated.

param(
    [string]$ProjectId = "your-gcp-project",
    [string]$Region = "us-central1",
    [string]$Service = "acme-scoping"
)

$ErrorActionPreference = "Stop"

function Read-DotEnv {
    param([string]$Path)
    $map = @{}
    if (-not (Test-Path $Path)) {
        return $map
    }
    foreach ($raw in Get-Content $Path) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith("#")) { continue }
        $eq = $line.IndexOf("=")
        if ($eq -lt 1) { continue }
        $map[$line.Substring(0, $eq).Trim()] = $line.Substring($eq + 1).Trim()
    }
    return $map
}

function Ensure-Secret {
    param([string]$Name, [string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllText($tmp, $Value)
        # First deploy: secret does not exist yet. gcloud writes NOT_FOUND to
        # stderr and PowerShell treats that as a terminating error unless we
        # suppress it and rely on exit code instead of output.
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        gcloud secrets describe $Name --project $ProjectId --format="value(name)" 2>$null | Out-Null
        $exists = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = $prevEap
        if ($exists) {
            gcloud secrets versions add $Name --project $ProjectId --data-file $tmp --quiet | Out-Null
        } else {
            gcloud secrets create $Name --project $ProjectId --data-file $tmp --replication-policy automatic --quiet | Out-Null
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to write secret '$Name' (gcloud exit $LASTEXITCODE)."
        }
    } finally {
        Remove-Item $tmp -ErrorAction SilentlyContinue
    }
    return $true
}

Write-Host "Project: $ProjectId"
Write-Host "Region:  $Region"
Write-Host "Service: $Service"
gcloud config set project $ProjectId --quiet

Write-Host "Enabling APIs..."
gcloud services enable `
    run.googleapis.com `
    artifactregistry.googleapis.com `
    cloudbuild.googleapis.com `
    secretmanager.googleapis.com `
    firestore.googleapis.com `
    sheets.googleapis.com `
    --project $ProjectId
if ($LASTEXITCODE -ne 0) {
    Write-Host "API enable failed. Cloud Run needs billing on this project:"
    Write-Host "  https://console.cloud.google.com/billing/linkedaccount?project=$ProjectId"
    exit 1
}

$envMap = Read-DotEnv ".env"
$gemini = $envMap["GEMINI_API_KEY"]
$sheetId = $envMap["BUDGET_SPREADSHEET_ID"]
$mailKey = $envMap["MAIL_API_KEY"]
$mailFrom = $envMap["MAIL_FROM_ADDRESS"]
$sessionSecret = $envMap["SESSION_TOKEN_SECRET"]
$password = $envMap["INTERNAL_ACCESS_PASSWORD"]

if ([string]::IsNullOrWhiteSpace($sessionSecret)) {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $sessionSecret = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    Write-Host "Generated SESSION_TOKEN_SECRET (stored in Secret Manager, not printed)."
}

if ([string]::IsNullOrWhiteSpace($password)) {
    $passwordFile = "secrets/cloud-run-password.txt"
    if (Test-Path $passwordFile) {
        $password = (Get-Content $passwordFile -Raw).Trim()
        Write-Host "Reusing INTERNAL_ACCESS_PASSWORD from secrets/cloud-run-password.txt"
    }
}
if ([string]::IsNullOrWhiteSpace($password)) {
    $password = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 18 | ForEach-Object { [char]$_ })
    $secretsDir = "secrets"
    if (-not (Test-Path $secretsDir)) {
        New-Item -ItemType Directory -Path $secretsDir | Out-Null
    }
    Set-Content -Path "$secretsDir/cloud-run-password.txt" -Value $password -NoNewline
    Write-Host "Generated INTERNAL_ACCESS_PASSWORD -> secrets/cloud-run-password.txt"
}

Write-Host "Writing secrets (values not printed)..."
$secretFlags = @(
    "SESSION_TOKEN_SECRET=acme-session-token-secret:latest",
    "INTERNAL_ACCESS_PASSWORD=acme-internal-access-password:latest"
)
Ensure-Secret "acme-session-token-secret" $sessionSecret | Out-Null
Ensure-Secret "acme-internal-access-password" $password | Out-Null
if (Ensure-Secret "acme-gemini-api-key" $gemini) {
    $secretFlags += "GEMINI_API_KEY=acme-gemini-api-key:latest"
} else {
    Write-Host "No GEMINI_API_KEY in .env; hosted answers will be deterministic."
}
if (Ensure-Secret "acme-mail-api-key" $mailKey) {
    $secretFlags += "MAIL_API_KEY=acme-mail-api-key:latest"
}

$projectNumber = gcloud projects describe $ProjectId --format="value(projectNumber)"
$runtimeSa = "$projectNumber-compute@developer.gserviceaccount.com"
Write-Host "Runtime service account: $runtimeSa"

gcloud projects add-iam-policy-binding $ProjectId `
    --member "serviceAccount:$runtimeSa" `
    --role "roles/secretmanager.secretAccessor" `
    --quiet | Out-Null

gcloud projects add-iam-policy-binding $ProjectId `
    --member "serviceAccount:$runtimeSa" `
    --role "roles/datastore.user" `
    --quiet | Out-Null

$envVars = @(
    "ENVIRONMENT=production",
    "GCP_PROJECT_ID=$ProjectId",
    "AUDIT_BACKEND=auto",
    "USE_LLM_PLANNER=true",
    "USE_LLM_COMPOSER=true"
)
if (-not [string]::IsNullOrWhiteSpace($sheetId)) {
    $envVars += "BUDGET_SPREADSHEET_ID=$sheetId"
}
if (-not [string]::IsNullOrWhiteSpace($mailFrom)) {
    $envVars += "MAIL_FROM_ADDRESS=$mailFrom"
}

Write-Host "Building and deploying (Cloud Build + Cloud Run). This takes a few minutes..."
gcloud run deploy $Service `
    --project $ProjectId `
    --region $Region `
    --source . `
    --allow-unauthenticated `
    --memory 1Gi `
    --cpu 1 `
    --timeout 60 `
    --concurrency 20 `
    --min-instances 0 `
    --max-instances 3 `
    --cpu-boost `
    --set-env-vars ($envVars -join ",") `
    --set-secrets ($secretFlags -join ",") `
    --quiet

$url = gcloud run services describe $Service --project $ProjectId --region $Region --format="value(status.url)"
Write-Host ""
Write-Host "Deployed: $url"
Write-Host "Health:   $url/api/health"
Write-Host ""
Write-Host "Share the live Google Sheet as Viewer with:"
Write-Host "  $runtimeSa"
Write-Host "Log in on the chat page with INTERNAL_ACCESS_PASSWORD from .env"
Write-Host "(or secrets/cloud-run-password.txt if one was generated)."
