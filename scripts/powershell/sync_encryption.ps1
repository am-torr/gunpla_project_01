Param(
    [string]$SourceContainer = "gunpla-n8n",
    [string]$ComposeFilePath = ""  # Path to main machine's docker-compose.yml
)

# Step 1: Extract key from source container
$encryptionKey = docker exec $SourceContainer printenv N8N_ENCRYPTION_KEY 2>$null
$encryptionKey = $encryptionKey.Trim()

if ([string]::IsNullOrWhiteSpace($encryptionKey)) {
    Write-Host "N8N_ENCRYPTION_KEY env var not set. Reading from internal config file..." -ForegroundColor Yellow
    $configRaw = docker exec $SourceContainer cat /home/node/.n8n/config 2>$null
    if ($configRaw -match '"encryptionKey":\s*"([^"]+)"') {
        $encryptionKey = $matches[1]
    } else {
        Write-Error "Could not extract encryption key from container '$SourceContainer'. Aborting."
        exit 1
    }
}

Write-Host "Encryption key extracted successfully." -ForegroundColor Green

# Step 2: Write key to target docker-compose.yml
if ([string]::IsNullOrWhiteSpace($ComposeFilePath) -or !(Test-Path $ComposeFilePath)) {
    Write-Error "Please provide a valid -ComposeFilePath to the destination docker-compose.yml."
    exit 1
}

$content = Get-Content $ComposeFilePath -Raw

if ($content -match 'N8N_ENCRYPTION_KEY=.+') {
    # Replace existing key
    $updated = $content -replace 'N8N_ENCRYPTION_KEY=.+', "N8N_ENCRYPTION_KEY=$encryptionKey"
    Write-Host "Existing N8N_ENCRYPTION_KEY replaced." -ForegroundColor Cyan
} else {
    Write-Warning "N8N_ENCRYPTION_KEY not found in compose file. Please add it manually under the environment section:"
    Write-Host "  - N8N_ENCRYPTION_KEY=$encryptionKey" -ForegroundColor Magenta
    exit 0
}

Set-Content $ComposeFilePath $updated
Write-Host "docker-compose.yml updated at: $ComposeFilePath" -ForegroundColor Green
Write-Host "Next step: Run 'docker compose down && docker compose up -d' on the main machine to apply the new key."