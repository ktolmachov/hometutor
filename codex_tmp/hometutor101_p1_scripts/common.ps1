Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    param([string]$RepoRoot = "D:\Projects\hometutor-studio")
    $resolved = [System.IO.Path]::GetFullPath($RepoRoot)
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "Repo root not found: $resolved"
    }
    return $resolved
}

function Resolve-RuntimeRoot {
    param([string]$RuntimeRepoRoot = "D:\Projects\hometutor")
    $resolved = [System.IO.Path]::GetFullPath($RuntimeRepoRoot)
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "Runtime repo root not found: $resolved"
    }
    return $resolved
}

function Get-StudioPython {
    param([string]$RepoRoot)
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        return $venvPython
    }
    return "python"
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = (Get-Location).Path,
        [hashtable]$Environment = @{}
    )
    Write-Host ""
    Write-Host ">> $FilePath $($Arguments -join ' ')" -ForegroundColor Cyan
    $old = @{}
    foreach ($key in $Environment.Keys) {
        $old[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        [Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], "Process")
    }
    try {
        Push-Location $WorkingDirectory
        try {
            & $FilePath @Arguments
            $exit = if ($LASTEXITCODE -is [int]) { $LASTEXITCODE } else { 0 }
            if ($exit -ne 0) {
                throw "Command failed with exit code ${exit}: $FilePath $($Arguments -join ' ')"
            }
        } finally {
            Pop-Location
        }
    } finally {
        foreach ($key in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable($key, $old[$key], "Process")
        }
    }
}

function Assert-ChildPath {
    param(
        [Parameter(Mandatory=$true)][string]$Parent,
        [Parameter(Mandatory=$true)][string]$Child
    )
    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\')
    $childFull = [System.IO.Path]::GetFullPath($Child)
    if (-not $childFull.StartsWith($parentFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Resolved path escapes parent. Parent=$parentFull Child=$childFull"
    }
    return $childFull
}

function Get-RunName {
    param([string]$Run = "")
    if ($Run.Trim()) {
        if ($Run -notmatch '^\d{4}-\d{2}-\d{2}$') {
            throw "Run must be YYYY-MM-DD, got: $Run"
        }
        return $Run
    }
    return (Get-Date -Format "yyyy-MM-dd")
}

function Get-FinalScreenshotPath {
    param(
        [Parameter(Mandatory=$true)][string]$RepoRoot,
        [Parameter(Mandatory=$true)][string]$RelativeFrame
    )
    $clean = $RelativeFrame.Replace("/", "\").TrimStart("\")
    return Join-Path (Join-Path $RepoRoot "doc\screenshots\final") $clean
}

function Get-CourseDir {
    param(
        [string]$RepoRoot,
        [string]$CourseDir = "doc\courses\hometutor_101"
    )
    $path = Join-Path $RepoRoot $CourseDir
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "Course dir not found: $path"
    }
    return $path
}

function Get-GitShortHead {
    param([string]$RepoRoot)
    try {
        Push-Location $RepoRoot
        try {
            $head = (& git rev-parse --short HEAD 2>$null)
            if ($LASTEXITCODE -eq 0) { return ($head | Select-Object -First 1) }
        } finally {
            Pop-Location
        }
    } catch {
        return "<git unavailable>"
    }
    return "<git unavailable>"
}

function Write-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail = "")
    $mark = if ($Ok) { "OK" } else { "FAIL" }
    $color = if ($Ok) { "Green" } else { "Red" }
    Write-Host ("{0,-5} {1} {2}" -f $mark, $Name, $Detail) -ForegroundColor $color
}
