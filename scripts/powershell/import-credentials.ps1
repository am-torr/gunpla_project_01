Param(
    [string]$ContainerName = "gunpla-n8n"
)

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$hostPath = Join-Path $RepoRoot "workflows\credentials-export.json"

if (-not (Test-Path $hostPath)) {
    Write-Error "File not found: $hostPath. Did you export credentials or git pull first?"
    exit 1
}

Write-Host "Importing credentials into container '$ContainerName' from $hostPath..." -ForegroundColor Cyan

docker exec -it $ContainerName `
  n8n import:credentials --input=/home/node/.n8n/workflows/credentials-export.json

if ($LASTEXITCODE -ne 0) {
    Write-Error "n8n import:credentials failed."
    exit $LASTEXITCODE
}

Write-Host "Credential import completed." -ForegroundColor Green