param(
    [string]$EnvFilePath = "C:\PROJECTS\gunpla-tracker-verified\.env",
    [string]$ComposeFilePath = "C:\PROJECTS\gunpla-tracker-verified\docker-compose.yml",
    [string]$CredentialsFilePath = "C:\PROJECTS\gunpla-tracker-verified\workflows\credentials-export.json",
    [string]$SourceEncryptionKey,
    [string]$ContainerName = "gunpla-n8n",
    [string]$N8nDataVolumeName = "n8n-data"
)

if ([string]::IsNullOrWhiteSpace($SourceEncryptionKey)) {
    Write-Error "You must pass -SourceEncryptionKey with the exact key from the source machine."
    exit 1
}

if (!(Test-Path $ComposeFilePath)) {
    Write-Error "docker-compose.yml not found: $ComposeFilePath"
    exit 1
}

if (!(Test-Path $CredentialsFilePath)) {
    Write-Error "Credentials export file not found: $CredentialsFilePath"
    exit 1
}

Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host "  Sync n8n encryption key (.env + config + credentials)   " -ForegroundColor Yellow
Write-Host "=========================================================" -ForegroundColor Cyan

Write-Host "`nStep 0: Ensure compose uses .env for N8N_ENCRYPTION_KEY..." -ForegroundColor Cyan
Write-Host "Expected structure under services.n8n:" -ForegroundColor Gray
Write-Host ""
Write-Host "services:"
Write-Host "  n8n:"
Write-Host "    env_file:"
Write-Host "      - .env"
Write-Host "    environment:"
Write-Host "      N8N_ENCRYPTION_KEY: `"${N8N_ENCRYPTION_KEY}`""
Write-Host ""

$confirmation = Read-Host "Is docker-compose.yml structured like that under services.n8n? (Y/N)"
if ($confirmation -notmatch '^[Yy]$') {
    Write-Warning "Fix docker-compose.yml structure first, then rerun this script."
    exit 0
}

Write-Host "`nStep 1: Syncing N8N_ENCRYPTION_KEY into .env with hash check..." -ForegroundColor Cyan

$envDir = Split-Path $EnvFilePath -Parent
if (!(Test-Path $envDir)) {
    Write-Host "Creating directory for .env: $envDir" -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $envDir -Force | Out-Null
}

[string]$beforeHash = "<none>"
if (Test-Path $EnvFilePath) {
    $beforeHash = (Get-FileHash -Algorithm SHA256 -Path $EnvFilePath).Hash
    Write-Host "Current .env SHA256: $beforeHash" -ForegroundColor DarkGray
} else {
    Write-Host ".env does not exist yet; it will be created." -ForegroundColor Yellow
}

if (!(Test-Path $EnvFilePath)) {
    Set-Content -Path $EnvFilePath -Value "N8N_ENCRYPTION_KEY=$SourceEncryptionKey" -Encoding UTF8
    Write-Host ".env file created with N8N_ENCRYPTION_KEY." -ForegroundColor Green
} else {
    $envContent = Get-Content $EnvFilePath -Raw

    if ($envContent -match '(?m)^N8N_ENCRYPTION_KEY=.*$') {
        $envContent = [regex]::Replace(
            $envContent,
            '(?m)^(N8N_ENCRYPTION_KEY=).*$',
            "`$1$SourceEncryptionKey"
        )
        Set-Content -Path $EnvFilePath -Value $envContent -Encoding UTF8
        Write-Host "Updated existing N8N_ENCRYPTION_KEY in .env." -ForegroundColor Green
    } else {
        $appendString = "`nN8N_ENCRYPTION_KEY=$SourceEncryptionKey"
        Add-Content -Path $EnvFilePath -Value $appendString -Encoding UTF8
        Write-Host "Appended N8N_ENCRYPTION_KEY to .env." -ForegroundColor Green
    }
}

if (Test-Path $EnvFilePath) {
    [string]$afterHash = (Get-FileHash -Algorithm SHA256 -Path $EnvFilePath).Hash
    Write-Host "New .env SHA256:     $afterHash" -ForegroundColor DarkGray

    if ($beforeHash -ne "<none>" -and $beforeHash -eq $afterHash) {
        Write-Warning "Hash did not change; .env contents appear identical. Double-check N8N_ENCRYPTION_KEY manually."
    } else {
        Write-Host "Hash changed successfully; .env was modified." -ForegroundColor Cyan
    }
} else {
    Write-Error ".env still does not exist after attempted creation. Aborting."
    exit 1
}

Write-Host "`nStep 1.5: Ensuring docker-compose.yml N8N_ENCRYPTION_KEY uses .env value..." -ForegroundColor Cyan

$composeLines = Get-Content $ComposeFilePath
$composeLines = $composeLines -replace '^(\s*N8N_ENCRYPTION_KEY\s*:\s*).*$','${1}"${N8N_ENCRYPTION_KEY}"'
Set-Content -Path $ComposeFilePath -Value $composeLines -Encoding UTF8

Write-Host 'docker-compose.yml N8N_ENCRYPTION_KEY entry updated to use "${N8N_ENCRYPTION_KEY}" (env-based).' -ForegroundColor Green

Write-Host "`nStep 2: Overwriting /home/node/.n8n/config in volume with the same key..." -ForegroundColor Cyan

# Build JSON string in PowerShell
$json = '{"encryptionKey":"' + $SourceEncryptionKey + '"}'

# Use literal printf in the container; this avoids BOM and CRLF
$script = "printf '" + $json + "' > /home/node/.n8n/config"

docker run --rm `
  -v "${N8nDataVolumeName}:/home/node/.n8n" `
  alpine /bin/sh -c "$script"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to write /home/node/.n8n/config in volume $N8nDataVolumeName."
    exit $LASTEXITCODE
}

Write-Host "Config file in volume $N8nDataVolumeName updated with the same encryption key." -ForegroundColor Green

Write-Host "`nStep 3: Restarting n8n stack..." -ForegroundColor Cyan
$composeDir = Split-Path $ComposeFilePath -Parent

docker compose --project-directory $composeDir down
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker compose down failed."
    exit $LASTEXITCODE
}

docker compose --project-directory $composeDir up -d
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker compose up -d failed."
    exit $LASTEXITCODE
}

Write-Host "Waiting 15 seconds for n8n to initialize..." -ForegroundColor Cyan
Start-Sleep -Seconds 15

Write-Host "`nStep 4: Verifying env var inside the container..." -ForegroundColor Cyan
docker exec $ContainerName printenv N8N_ENCRYPTION_KEY
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to read N8N_ENCRYPTION_KEY from container $ContainerName. Is it running?"
    exit $LASTEXITCODE
}

Write-Host "`nStep 5: Copying credentials file into the container..." -ForegroundColor Cyan
docker cp $CredentialsFilePath "${ContainerName}:/tmp/credentials-export.json"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to copy credentials file into container."
    exit $LASTEXITCODE
}

Write-Host "`nStep 6: Importing encrypted credentials..." -ForegroundColor Cyan
$importResult = docker exec $ContainerName n8n import:credentials --input=/tmp/credentials-export.json 2>&1
$exitCode = $LASTEXITCODE
Write-Host $importResult

if ($exitCode -ne 0) {
    Write-Warning "n8n import:credentials exited with code $exitCode. See output above for details."
} else {
    Write-Host "Credentials import completed successfully." -ForegroundColor Green
}

Write-Host "`nDone. .env, config, and credentials are now synced with the source encryption key." -ForegroundColor Green