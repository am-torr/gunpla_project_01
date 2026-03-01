param(
    [string]$RootPath = 'D:\PROJECT\gunpla-tracker-verified'
)

if (-not (Test-Path -Path $RootPath -PathType Container)) {
    Write-Error "Root path '$RootPath' does not exist or is not a directory."
    exit 1
}

# Exclusion patterns
$excludeNamePatterns = @('*backup*', '*bk*')     # applies to files and folders (case-insensitive)
$excludeDirNames     = @('.mypy_cache', '.pytest_cache', '__pycache__')

function Test-IsExcluded {
    param(
        [System.IO.FileSystemInfo]$Item
    )

    $name = $Item.Name

    # Exclude cache/system directories by exact name
    if ($Item.PSIsContainer -and ($excludeDirNames -contains $name)) {
        return $true
    }

    # Exclude anything with backup/bk in its name
    foreach ($pattern in $excludeNamePatterns) {
        if ($name -like $pattern) {
            return $true
        }
    }

    return $false
}

function Get-FilteredChildren {
    param(
        [string]$Path,
        [switch]$FilesOnly,
        [switch]$DirectoriesOnly
    )

    $items = Get-ChildItem -Path $Path -Force -ErrorAction SilentlyContinue

    if ($FilesOnly) {
        $items = $items | Where-Object { -not $_.PSIsContainer }
    } elseif ($DirectoriesOnly) {
        $items = $items | Where-Object { $_.PSIsContainer }
    }

    $items | Where-Object { -not (Test-IsExcluded -Item $_) }
}

function Get-FolderStats {
    param(
        [string]$FolderPath
    )

    $allFiles = Get-ChildItem -Path $FolderPath -File -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { -not (Test-IsExcluded -Item $_) }

    $fileCount = $allFiles.Count
    $totalSize = 0

    if ($fileCount -gt 0) {
        $totalSize = ($allFiles | Measure-Object -Property Length -Sum).Sum
    }

    [PSCustomObject]@{
        Folder      = ($FolderPath -replace [regex]::Escape($RootPath), '').Trim('\')
        FileCount   = $fileCount
        TotalSizeMB = [math]::Round($totalSize / 1MB, 2)
    }
}

function Show-Tree {
    param(
        [string]$Path,
        [string]$Prefix = ''
    )

    $dirs  = Get-FilteredChildren -Path $Path -DirectoriesOnly | Sort-Object Name
    $files = Get-FilteredChildren -Path $Path -FilesOnly       | Sort-Object Name

    $total = $dirs.Count + $files.Count
    $index = 0

    foreach ($dir in $dirs) {
        $index++
        $isLast = ($index -eq $total)
        $branch = if ($isLast) { '└── ' } else { '├── ' }

        Write-Host "$Prefix$branch$($dir.Name)"

        $nextPrefix = if ($isLast) { "$Prefix    " } else { "$Prefix│   " }
        Show-Tree -Path $dir.FullName -Prefix $nextPrefix
    }

    foreach ($file in $files) {
        $index++
        $isLast = ($index -eq $total)
        $branch = if ($isLast) { '└── ' } else { '├── ' }

        Write-Host "$Prefix$branch$($file.Name)"
    }
}

Write-Host "Project root: $RootPath"
Write-Host ""
Write-Host "=== Folder summary (immediate children) ==="
Write-Host ""

$topLevelDirs = Get-FilteredChildren -Path $RootPath -DirectoriesOnly | Sort-Object Name

$stats = foreach ($dir in $topLevelDirs) {
    Get-FolderStats -FolderPath $dir.FullName
}

$stats | Format-Table -AutoSize

Write-Host ""
Write-Host "=== Project tree (after exclusions) ==="
Write-Host ""

Write-Host "."
Show-Tree -Path $RootPath -Prefix ""
