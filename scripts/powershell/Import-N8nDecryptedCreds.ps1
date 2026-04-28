param(
    # docker-compose service name
    [string]$ServiceName = "n8n",

    # Path to the JSON file inside the container
    [string]$InputPathInContainer = "/home/node/.n8n/decrypted-creds.json"
)

Write-Host "Importing credentials into service '$ServiceName' from '$InputPathInContainer'..."

# Run the n8n CLI inside the Docker container
docker compose exec $ServiceName n8n import:credentials --input=$InputPathInContainer

if ($LASTEXITCODE -ne 0) {
    Write-Error "n8n import:credentials failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "Import completed."