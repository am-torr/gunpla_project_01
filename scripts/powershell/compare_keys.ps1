param(
    [string]$ContainerName    = "gunpla-n8n",
    [string]$N8nDataVolumeName = "n8n-data",
    [string]$OutputPath        = ".\key-compare.txt"
)

Write-Host "=== Extracting both keys to $OutputPath ===" -ForegroundColor Cyan

# 1) Get env key from container
$envKey = docker exec $ContainerName printenv N8N_ENCRYPTION_KEY 2>$null

# 2) Get raw config from volume
$configRaw = docker run --rm `
    -v "${N8nDataVolumeName}:/home/node/.n8n" `
    alpine /bin/sh -c "cat /home/node/.n8n/config" 2>$null

# 3) Dump both to plain text file
"ENV KEY:"    | Set-Content  $OutputPath -Encoding ASCII
$envKey       | Add-Content  $OutputPath -Encoding ASCII
""            | Add-Content  $OutputPath -Encoding ASCII
"CONFIG RAW:" | Add-Content  $OutputPath -Encoding ASCII
$configRaw    | Add-Content  $OutputPath -Encoding ASCII

Write-Host "Written to $OutputPath" -ForegroundColor Green
Write-Host ""
Write-Host "--- ENV KEY ---"    -ForegroundColor Yellow
Write-Host $envKey
Write-Host ""
Write-Host "--- CONFIG RAW ---" -ForegroundColor Yellow
Write-Host $configRaw