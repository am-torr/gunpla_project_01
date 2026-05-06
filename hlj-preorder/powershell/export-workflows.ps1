Param(
    [string]$ContainerName = "gunpla-n8n"
)

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$hostPath = Join-Path $RepoRoot "workflows\workflows-export.json"

Write-Host "Exporting workflows from container '$ContainerName'..." -ForegroundColor Cyan

docker exec -it $ContainerName `
  n8n export:workflow --all --output=/home/node/.n8n/workflows/workflows-export.json

if ($LASTEXITCODE -ne 0) {
    Write-Error "n8n export:workflow failed."
    exit $LASTEXITCODE
}

if (Test-Path $hostPath) {
    Write-Host "Export completed. File is at: $hostPath" -ForegroundColor Green
} else {
    Write-Warning "Export command succeeded, but workflows-export.json was not found at $hostPath. Check your volume mapping."
}