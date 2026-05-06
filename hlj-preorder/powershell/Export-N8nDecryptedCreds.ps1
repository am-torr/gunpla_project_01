param(
    [string]$ServiceName = "n8n",
    [string]$OutputPathInContainer = "/home/node/.n8n/decrypted-creds.json"
)

Write-Host "Exporting decrypted credentials from service '$ServiceName' to '$OutputPathInContainer'..."

# Run the n8n CLI inside the Docker container
docker compose exec $ServiceName n8n export:credentials --all --decrypted --output=$OutputPathInContainer

if ($LASTEXITCODE -ne 0) {
    Write-Error "n8n export:credentials failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "Export completed."