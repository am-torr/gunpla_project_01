param(
    # docker-compose service name
    [string]$ServiceName = "n8n",

    # Path to the JSON file on Windows (n8n root folder)
    [string]$LocalJsonPath = "D:\PROJECT\gunpla-tracker-verified\credentials-decrypted.json",

    # Path to the JSON file inside the container
    [string]$InputPathInContainer = "/home/node/.n8n/decrypted-creds.json"
)

Write-Host "Importing credentials into service '$ServiceName'..."
Write-Host "Local JSON: $LocalJsonPath"
Write-Host "Container JSON path: $InputPathInContainer"

# Resolve local path and verify file exists
$resolvedLocalPath = Resolve-Path -Path $LocalJsonPath -ErrorAction SilentlyContinue
if (-not $resolvedLocalPath) {
    Write-Error "Local JSON file not found at '$LocalJsonPath'."
    exit 1
}

# Get container name for the service (first matching container)
$containerName = (docker ps --format "{{.Names}}" | Where-Object { $_ -like "*$ServiceName*" } | Select-Object -First 1)

if (-not $containerName) {
    Write-Error "No running container found for service name pattern '*$ServiceName*'."
    exit 1
}

Write-Host "Using container: $containerName"

# Copy JSON into the container
Write-Host "Copying local file to container..."
docker cp $resolvedLocalPath "`"$containerName`:$InputPathInContainer`""

if ($LASTEXITCODE -ne 0) {
    Write-Error "docker cp failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

# Run the n8n CLI inside the Docker container
Write-Host "Running n8n import:credentials inside container..."
docker compose exec $ServiceName n8n import:credentials --input=$InputPathInContainer

if ($LASTEXITCODE -ne 0) {
    Write-Error "n8n import:credentials failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "Import completed successfully."