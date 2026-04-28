# Get Encryption Key from n8n Container
param(
    [string]$SourceContainer = "gunpla-n8n"
)

Write-Host "Attempting to retrieve encryption key from container '$SourceContainer'..." -ForegroundColor Cyan

# Step 1: Try to get from environment variables
$encryptionKey = docker exec $SourceContainer printenv N8N_ENCRYPTION_KEY 2>$null

if ($encryptionKey) {
    $encryptionKey = $encryptionKey.Trim()
    if (-not [string]::IsNullOrWhiteSpace($encryptionKey)) {
        Write-Host "Found N8N_ENCRYPTION_KEY in environment variables." -ForegroundColor Green
        Write-Host "Encryption Key: $encryptionKey" -ForegroundColor Yellow
        exit 0
    }
}

# Step 2: If not found in env, try to read from config file
Write-Host "N8N_ENCRYPTION_KEY not found in environment. Trying to read from config file..." -ForegroundColor Yellow
$configRaw = docker exec $SourceContainer cat /home/node/.n8n/config 2>$null

if ($configRaw) {
    # Try to parse as JSON
    try {
        $config = $configRaw | ConvertFrom-Json
        if ($config.encryptionKey) {
            $encryptionKey = $config.encryptionKey.Trim()
            if (-not [string]::IsNullOrWhiteSpace($encryptionKey)) {
                Write-Host "Encryption key extracted from config file (via JSON parsing)." -ForegroundColor Green
                Write-Host "Encryption Key: $encryptionKey" -ForegroundColor Yellow
                exit 0
            }
        }
    } catch {
        # JSON parsing failed, try regex as fallback
        Write-Host "Config file is not valid JSON. Trying regex extraction..." -ForegroundColor Yellow
        if ($configRaw -match '"encryptionKey":\s*"([^"]+)"') {
            $encryptionKey = $matches[1].Trim()
            if (-not [string]::IsNullOrWhiteSpace($encryptionKey)) {
                Write-Host "Encryption key extracted from config file (via regex)." -ForegroundColor Green
                Write-Host "Encryption Key: $encryptionKey" -ForegroundColor Yellow
                exit 0
            }
        }
    }
}

# If we get here, we failed to get the key
Write-Error "Could not retrieve encryption key from container '$SourceContainer'. Check that the container is running and the config file exists at /home/node/.n8n/config." -ForegroundColor Red
exit 1