param(
    [string]$ComposeFilePath = "C:\PROJECTS\gunpla-tracker-verified\docker-compose.yml",
    [string]$CredentialsFilePath = "C:\PROJECTS\gunpla-tracker-verified\workflows\credentials-export.json",
    [string]$SourceEncryptionKey,
    [string]$ContainerName = "gunpla-n8n"
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

Write-Host "Step 1: Syncing encryption key into docker-compose.yml..." -ForegroundColor Cyan
$content = Get-Content $ComposeFilePath -Raw

if ($content -match '(?m)^\s*N8N_ENCRYPTION_KEY\s*:\s*.*$') {
    $content = [regex]::Replace(
        $content,
        '(?m)^(\s*N8N_ENCRYPTION_KEY\s*:\s*).*$',
        "`$1`"$SourceEncryptionKey`""
    )
    Write-Host "Updated existing map-style N8N_ENCRYPTION_KEY entry." -ForegroundColor Green
}
elseif ($content -match '(?m)^\s*-\s*N8N_ENCRYPTION_KEY=.*$') {
    $escapedKey = $SourceEncryptionKey -replace '\\', '\\' -replace '\$', '$$'
    $content = [regex]::Replace(
        $content,
        '(?m)^(\s*-\s*N8N_ENCRYPTION_KEY=).*$',
        "`$1$escapedKey"
    )
    Write-Host "Updated existing list-style N8N_ENCRYPTION_KEY entry." -ForegroundColor Green
}
else {
    Write-Warning "N8N_ENCRYPTION_KEY was not found in docker-compose.yml."
    Write-Warning "Add this under the n8n service environment section, then rerun:"
    Write-Host '  N8N_ENCRYPTION_KEY: "<paste-key-here>"' -ForegroundColor Yellow
    exit 1
}

Set-Content -Path $ComposeFilePath -Value $content -Encoding UTF8
Write-Host "docker-compose.yml updated." -ForegroundColor Green

Write-Host "Step 2: Restarting n8n with the synced key..." -ForegroundColor Cyan
$composeDir = Split-Path $ComposeFilePath -Parent

Push-Location $composeDir
docker compose down
if ($LASTEXITCODE -ne 0) {
    Pop-Location
    Write-Error "docker compose down failed."
    exit $LASTEXITCODE
}

docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Pop-Location
    Write-Error "docker compose up -d failed."
    exit $LASTEXITCODE
}
Pop-Location

Write-Host "Step 3: Copying credentials file into the container..." -ForegroundColor Cyan
docker cp $CredentialsFilePath "${ContainerName}:/tmp/credentials-export.json"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to copy credentials file into container."
    exit $LASTEXITCODE
}

Write-Host "Step 4: Importing encrypted credentials..." -ForegroundColor Cyan
docker exec $ContainerName n8n import:credentials --input=/tmp/credentials-export.json
if ($LASTEXITCODE -ne 0) {
    Write-Error "n8n import:credentials failed."
    exit $LASTEXITCODE
}

Write-Host "Done. The destination machine is now using the source encryption key and the credentials import completed." -ForegroundColor Green