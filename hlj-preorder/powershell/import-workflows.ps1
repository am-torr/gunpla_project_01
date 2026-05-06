Param(
    [string]$ContainerName = "gunpla-n8n"
)

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$hostPath = Join-Path $RepoRoot "workflows\workflows-export.json"

if (-not (Test-Path $hostPath)) {
    Write-Error "File not found: $hostPath. Did you export or git pull first?"
    exit 1
}

Write-Host "Importing workflows into container '$ContainerName' from $hostPath..." -ForegroundColor Cyan

docker exec -it $ContainerName `
  n8n import:workflow --input=/home/node/.n8n/workflows/workflows-export.json

if ($LASTEXITCODE -ne 0) {
    Write-Error "n8n import:workflow failed."
    exit $LASTEXITCODE
}

Write-Host "Import completed." -ForegroundColor Green