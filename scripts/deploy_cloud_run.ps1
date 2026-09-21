# Deploy the assistant to Cloud Run in us-central1 (fastest generic region).
#
# Usage (from the repo root, gcloud already logged in):
#   .\scripts\deploy_cloud_run.ps1
#
# Reads non-empty values from .env and stores secrets in Secret Manager.
# Does not print secret values. Generated credentials are written to
# gitignored files under secrets/ and reused on later runs, so redeploying
# neither rotates the session HMAC nor changes the login password.

param(
    [string]$ProjectId = "your-gcp-project",
    [string]$Region = "us-central1",
    [string]$Service = "acme-scoping"
)

$ErrorActionPreference = "Stop"

# The interpreter that builds the shipped index. Prefer the project venv, so a
# deploy uses the same dependencies everything else was checked against.
$Python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }

function Invoke-GCloud {
    # gcloud writes progress and advisories to stderr as a matter of course:
    # "Updated property [core/project]", API-enablement progress, and the ADC
    # quota-project notice. With $ErrorActionPreference = "Stop" PowerShell
    # treats any of that as a terminating error, so a cosmetic warning aborts
    # the deploy before the exit code is ever looked at. That is what happened
    # on 27 Aug, and it is the same trap that stopped the first-ever run on a
    # NOT_FOUND from `gcloud secrets describe`.
    #
    # Only the exit code says whether gcloud actually failed. Output is passed
    # through so callers can capture a --format value.
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GcloudArgs)

    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & gcloud @GcloudArgs 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) {
        $output | ForEach-Object { Write-Host $_ }
        throw "gcloud $($GcloudArgs -join ' ') failed (exit $code)."
    }
    return $output
}

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
        # A NOT_FOUND here is the expected first-run answer rather than a
        # failure, so this one call is checked by exit code directly instead of
        # going through Invoke-GCloud, which would raise on it.
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        gcloud secrets describe $Name --project $ProjectId --format="value(name)" 2>$null | Out-Null
        $exists = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = $prevEap

        # Both of these announce success on stderr - "Created version [4] of
        # the secret [...]" - so they need the same tolerance as everything
        # else. gcloud's idea of stderr is "anything that is not data".
        if ($exists) {
            Invoke-GCloud secrets versions add $Name --project $ProjectId --data-file $tmp --quiet | Out-Null
        } else {
            Invoke-GCloud secrets create $Name --project $ProjectId --data-file $tmp --replication-policy automatic --quiet | Out-Null
        }
    } finally {
        Remove-Item $tmp -ErrorAction SilentlyContinue
    }
    return $true
}

Write-Host "Project: $ProjectId"
Write-Host "Region:  $Region"
Write-Host "Service: $Service"
Invoke-GCloud config set project $ProjectId --quiet | Out-Null

Write-Host "Enabling APIs..."
try {
    Invoke-GCloud services enable `
        run.googleapis.com `
        artifactregistry.googleapis.com `
        cloudbuild.googleapis.com `
        secretmanager.googleapis.com `
        firestore.googleapis.com `
        sheets.googleapis.com `
        --project $ProjectId | Out-Null
} catch {
    Write-Host "API enable failed. Cloud Run needs billing on this project:"
    Write-Host "  https://console.cloud.google.com/billing/linkedaccount?project=$ProjectId"
    exit 1
}

$envMap = Read-DotEnv ".env"
$gemini = $envMap["GEMINI_API_KEY"]
$sheetId = $envMap["BUDGET_SPREADSHEET_ID"]
$mailKey = $envMap["MAIL_API_KEY"]
$mailFrom = $envMap["MAIL_FROM_ADDRESS"]
$mailRedirect = $envMap["MAIL_REDIRECT_TO"]
$sessionSecret = $envMap["SESSION_TOKEN_SECRET"]
$password = $envMap["INTERNAL_ACCESS_PASSWORD"]
$allowedOrigins = $envMap["ALLOWED_ORIGINS"]
$budgetTtl = $envMap["BUDGET_CACHE_TTL_SECONDS"]
$quoteTtl = $envMap["QUOTE_CACHE_TTL_SECONDS"]
$publicBaseUrl = $envMap["PUBLIC_BASE_URL"]

# Where the request emails fetch their logo and brand faces from. An email has
# no origin to resolve a relative path against, so both have to be absolute.
#
# Taken from .env when it is set, and otherwise from the service itself: a
# Cloud Run URL is stable for a service in a region, so after the first deploy
# it can simply be read back. Only the very first deploy has nowhere to read it
# from, and that one is patched after the service exists.
if ([string]::IsNullOrWhiteSpace($publicBaseUrl)) {
    $publicBaseUrl = (Invoke-GCloud run services describe $Service `
        --project $ProjectId --region $Region --format="value(status.url)" 2>$null) |
        Select-Object -Last 1
    if ($LASTEXITCODE -ne 0) { $publicBaseUrl = "" }
}

# The HMAC that signs session tokens. Every deploy used to mint a fresh one
# when .env had none, which silently logged out everyone still using the app.
# Reused from a gitignored file the same way the login password is, so it is
# generated once and then stays put.
$sessionFile = "secrets/session-token-secret.txt"
if ([string]::IsNullOrWhiteSpace($sessionSecret) -and (Test-Path $sessionFile)) {
    $sessionSecret = (Get-Content $sessionFile -Raw).Trim()
    Write-Host "Reusing SESSION_TOKEN_SECRET from $sessionFile (existing logins survive)."
}
if ([string]::IsNullOrWhiteSpace($sessionSecret)) {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $sessionSecret = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    if (-not (Test-Path "secrets")) {
        New-Item -ItemType Directory -Path "secrets" | Out-Null
    }
    Set-Content -Path $sessionFile -Value $sessionSecret -NoNewline
    Write-Host "Generated SESSION_TOKEN_SECRET -> $sessionFile (not printed)."
    Write-Host "  Anyone currently logged in will need to sign in again after this deploy."
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

$projectNumber = (Invoke-GCloud projects describe $ProjectId --format="value(projectNumber)") | Select-Object -Last 1
$runtimeSa = "$projectNumber-compute@developer.gserviceaccount.com"
Write-Host "Runtime service account: $runtimeSa"

Invoke-GCloud projects add-iam-policy-binding $ProjectId `
    --member "serviceAccount:$runtimeSa" `
    --role "roles/secretmanager.secretAccessor" `
    --quiet | Out-Null

Invoke-GCloud projects add-iam-policy-binding $ProjectId `
    --member "serviceAccount:$runtimeSa" `
    --role "roles/datastore.user" `
    --quiet | Out-Null

# The live recipients ship only here. The default path in config.py is the
# the agency stand-ins, so a dev machine, a test run or a forgotten script cannot
# email Sammy or Gabby: reaching them takes a deploy.
$envVars = @(
    "ENVIRONMENT=production",
    "GCP_PROJECT_ID=$ProjectId",
    "AUDIT_BACKEND=auto",
    "USE_LLM_PLANNER=true",
    "USE_LLM_COMPOSER=true",
    "CONTACTS_PATH=fixtures/contacts/production.json"
)
if (-not [string]::IsNullOrWhiteSpace($sheetId)) {
    $envVars += "BUDGET_SPREADSHEET_ID=$sheetId"
}
if (-not [string]::IsNullOrWhiteSpace($mailFrom)) {
    $envVars += "MAIL_FROM_ADDRESS=$mailFrom"
}
# Diverts every request email to one address instead of the Account or Country
# Manager. Announced rather than passed quietly, because a deploy that silently
# stops delivering to the people the tool exists to email is worth noticing.
if (-not [string]::IsNullOrWhiteSpace($mailRedirect)) {
    $envVars += "MAIL_REDIRECT_TO=$mailRedirect"
    Write-Host "MAIL_REDIRECT_TO is set: every request email goes to $mailRedirect, not to the AM or CM."
}
# Without this the CORS middleware is never installed, so the service answers
# only same-origin callers and a widget embedded on another domain fails in the
# browser before it reaches any of our code. Empty stays empty on purpose:
# that is the correct setting while the only page is the one this service
# serves itself.
if (-not [string]::IsNullOrWhiteSpace($allowedOrigins)) {
    $envVars += "ALLOWED_ORIGINS=$allowedOrigins"
}
# Both default sensibly in code, so these only travel when .env overrides them.
# Passed through because otherwise tuning how stale a figure may get would look
# like it worked locally and silently do nothing in production — the same trap
# ALLOWED_ORIGINS was in.
if (-not [string]::IsNullOrWhiteSpace($budgetTtl)) {
    $envVars += "BUDGET_CACHE_TTL_SECONDS=$budgetTtl"
}
if (-not [string]::IsNullOrWhiteSpace($quoteTtl)) {
    $envVars += "QUOTE_CACHE_TTL_SECONDS=$quoteTtl"
}
if (-not [string]::IsNullOrWhiteSpace($publicBaseUrl)) {
    $envVars += "PUBLIC_BASE_URL=$publicBaseUrl"
}

# Build the knowledge index here rather than inside the image.
#
# Embedding needs a Gemini key, and Cloud Build has none: that is the reason
# the deployed service ran keyword-only while every local check ran against
# vectors, which is exactly the kind of divergence that makes a green eval
# meaningless. Building it on the machine that deploys also means the index
# shipped is byte-identical to the one whoever ran this tested against.
#
# Without a key it falls back to keyword-only, which is a supported mode.
$indexPath = "artifacts/index.json"
if ([string]::IsNullOrWhiteSpace($gemini)) {
    Write-Host "No GEMINI_API_KEY in .env; building a keyword-only index."
    & $Python -m scripts.build_index --out $indexPath
} else {
    Write-Host "Building the knowledge index with embeddings..."
    $env:GEMINI_API_KEY = $gemini
    & $Python -m scripts.build_index --out $indexPath --embed
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "Index build failed. Fix that before deploying: the image ships this file."
    exit 1
}

# The env vars go through gcloud's ^delimiter^ escaping rather than a plain
# comma-joined list, because ALLOWED_ORIGINS is itself comma-separated and
# would otherwise truncate at the first origin.
#
# The delimiter is a pipe, not an @. MAIL_FROM_ADDRESS carries an email
# address, and @ split it mid-value into "Acme Scoping <onboarding" and
# "resend.dev>" — gcloud rejected the result and the deploy failed on 28 Aug.
# The separator has to be a character none of these values can hold: origins
# carry : and /, the sender carries @ < > and a space, spreadsheet ids carry
# - and _.
Write-Host "Building and deploying (Cloud Build + Cloud Run). This takes a few minutes..."
# Left as a direct call so Cloud Build progress streams to the console as it
# happens rather than being buffered until the end. It writes that progress to
# stderr, so the trap has to be lifted around it and the exit code checked.
$previousEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
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
    --set-env-vars ("^|^" + ($envVars -join "|")) `
    --set-secrets ($secretFlags -join ",") `
    --quiet
$deployCode = $LASTEXITCODE
$ErrorActionPreference = $previousEap
if ($deployCode -ne 0) {
    Write-Host ""
    Write-Host "Deploy failed (gcloud exit $deployCode). The previous revision is still serving."
    exit 1
}

$url = (Invoke-GCloud run services describe $Service --project $ProjectId --region $Region --format="value(status.url)") | Select-Object -Last 1
# First deploy only: the service had no URL to read before it existed, so the
# emails would have gone out with no logo and no brand faces. Every later
# deploy finds it already set and skips this, so it costs one extra revision
# once rather than one per deploy.
if ([string]::IsNullOrWhiteSpace($publicBaseUrl) -and -not [string]::IsNullOrWhiteSpace($url)) {
    Write-Host ""
    Write-Host "Setting PUBLIC_BASE_URL to $url (first deploy)."
    Invoke-GCloud run services update $Service `
        --project $ProjectId --region $Region `
        --update-env-vars "PUBLIC_BASE_URL=$url" --quiet | Out-Null
}

Write-Host ""
Write-Host "Deployed: $url"
Write-Host "Health:   $url/api/health"
Write-Host ""
Write-Host "Share the live Google Sheet as Viewer with:"
Write-Host "  $runtimeSa"
Write-Host "Log in on the chat page with INTERNAL_ACCESS_PASSWORD from .env"
Write-Host "(or secrets/cloud-run-password.txt if one was generated)."
