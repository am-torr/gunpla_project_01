Param(
    [string]$ContainerName = "gunpla-n8n"
)

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$hostPath = Join-Path $RepoRoot "workflows\credentials-export.json"

Write-Host "Exporting credentials from container '$ContainerName'..." -ForegroundColor Cyan

docker exec -it $ContainerName `
  n8n export:credentials --all --output=/home/node/.n8n/workflows/credentials-export.json

if ($LASTEXITCODE -ne 0) {
    Write-Error "n8n export:credentials failed."
    exit $LASTEXITCODE
}

if (Test-Path $hostPath) {
    Write-Host "Credential export completed. File is at: $hostPath" -ForegroundColor Green
} else {
    Write-Warning "Export command succeeded, but credentials-export.json was not found at $hostPath. Check your volume mapping."
}