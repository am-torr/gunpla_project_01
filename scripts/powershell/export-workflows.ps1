$container = "gunpla-n8n"
$insideFile = "/tmp/workflows-export.json"
$outsideFile = "..\..\workflows\workflows-export.json"

Write-Host "Exporting workflows from container '$container'..."

docker exec $container n8n export:workflow --backup --output=$insideFile
if ($LASTEXITCODE -ne 0) {
    Write-Error "n8n export:workflow failed."
    exit 1
}

docker cp "${container}:${insideFile}" $outsideFile
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker cp failed."
    exit 1
}

Write-Host "Export completed: $outsideFile"