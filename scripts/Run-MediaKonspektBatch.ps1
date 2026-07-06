<#
.SYNOPSIS
Пакетный прогон media-пайплайна для всех конспектов с видео в подпапке DATA_DIR.

.DESCRIPTION
Сканирует подпапку (напр. D:\AI\app\data\ИИ Агенты\), находит пары
<stem>.md + одноимённое видео (.mp4, .ts, …) и для каждой вызывает
Run-MediaKonspektPipeline.ps1 (remux → GPU ASR → sidecar).

Сопоставление: регистронезависимый stem файла. Конспекты без видео и видео
без конспекта выводятся в отчёт, но не обрабатываются.

.PARAMETER Folder
Абсолютный путь или data-relative подпапка внутри DATA_DIR,
напр. "ИИ Агенты" или "D:\AI\app\data\ИИ Агенты".

.PARAMETER Recurse
Искать .md и видео также во вложенных каталогах (по умолчанию — только верхний уровень).

.PARAMETER GpuIndex
Индекс GPU (по умолчанию 1 = вторая 5070 Ti).

.EXAMPLE
# План: показать пары без запуска
.\scripts\Run-MediaKonspektBatch.ps1 -Folder "ИИ Агенты" -WhatIf

.EXAMPLE
# Прогнать все уроки в подпапке
.\scripts\Run-MediaKonspektBatch.ps1 -Folder "D:\AI\app\data\ИИ Агенты" -GpuIndex 1

.EXAMPLE
# Пере-транскрибация + sidecar для всей папки
.\scripts\Run-MediaKonspektBatch.ps1 -Folder "ИИ Агенты" -Force

.EXAMPLE
# Только sidecar (ASR уже есть по всем урокам)
.\scripts\Run-MediaKonspektBatch.ps1 -Folder "ИИ Агенты" -SkipAsr
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [string]$Folder,

    [int]$GpuIndex = 1,

    [string]$Model = "large-v3",

    [string]$Language = "auto",

    [switch]$Recurse,

    [switch]$Remux,

    [switch]$Force,

    [switch]$InstallAsrExtra,

    [switch]$SkipAsr,

    [switch]$SkipSidecar,

    [switch]$DryRunSidecar,

    [switch]$StopOnError
)

$ErrorActionPreference = "Stop"

$MediaExtensions = @(
    ".mp4", ".ts", ".mts", ".m2ts", ".mkv", ".webm", ".mov", ".m4a", ".mp3", ".wav", ".ogg"
)
$SkipMdNames = @("readme.md", "index.md")

function Resolve-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Get-DataDir {
    param([string]$PythonExe, [string]$RepoRoot)

    $repoForPy = $RepoRoot.Replace("'", "''")
    $code = "import sys; sys.path.insert(0, r'$repoForPy'); from app.path_safety import resolve_data_relative_path; print(resolve_data_relative_path('.').resolve())"
    return (& $PythonExe -c $code).Trim()
}

function Resolve-DataFolder {
    param(
        [string]$RawFolder,
        [string]$DataDir
    )

    $candidate = $RawFolder.TrimEnd('\', '/')
    if ([System.IO.Path]::IsPathRooted($candidate)) {
        $abs = [System.IO.Path]::GetFullPath($candidate)
    } else {
        $abs = [System.IO.Path]::GetFullPath((Join-Path $DataDir ($candidate -replace '/', '\')))
    }

    $root = [System.IO.Path]::GetFullPath($DataDir).TrimEnd('\', '/')
    $inside = $abs.Equals($root, [System.StringComparison]::OrdinalIgnoreCase) -or
        $abs.StartsWith("$root\", [System.StringComparison]::OrdinalIgnoreCase)
    if (-not $inside) {
        throw "Папка вне DATA_DIR: $abs (корень: $root)"
    }
    if (-not (Test-Path -LiteralPath $abs)) {
        throw "Папка не найдена: $abs"
    }
    return $abs
}

function Get-DataRelativePath {
    param([string]$AbsolutePath, [string]$DataDir)

    $abs = [System.IO.Path]::GetFullPath($AbsolutePath)
    $root = [System.IO.Path]::GetFullPath($DataDir).TrimEnd('\', '/')
    $inside = $abs.Equals($root, [System.StringComparison]::OrdinalIgnoreCase) -or
        $abs.StartsWith("$root\", [System.StringComparison]::OrdinalIgnoreCase)
    if (-not $inside) {
        throw "Путь вне DATA_DIR: $abs (корень: $root)"
    }
    $rel = $abs.Substring($root.Length).TrimStart('\', '/')
    return ($rel -replace '\\', '/')
}

function Get-NormalizedStem {
    param([string]$Path)
    return [System.IO.Path]::GetFileNameWithoutExtension($Path).ToLowerInvariant()
}

function Find-MediaForStem {
    param(
        [string]$Stem,
        [hashtable]$MediaByStem,
        [string]$Directory = "",
        [bool]$SameDirectoryOnly = $false
    )

    if (-not $MediaByStem.ContainsKey($Stem)) {
        return $null
    }

    $candidates = $MediaByStem[$Stem]
    if ($SameDirectoryOnly) {
        $candidates = @($candidates | Where-Object {
            $_.DirectoryName.Equals($Directory, [System.StringComparison]::OrdinalIgnoreCase)
        })
        if ($candidates.Count -eq 0) {
            return $null
        }
    }
    # playable .mp4 предпочтительнее; иначе контейнер для remux; затем остальные форматы
    $priority = @{
        ".mp4"  = 0
        ".ts"   = 1
        ".mts"  = 2
        ".m2ts" = 3
        ".mkv"  = 4
        ".webm" = 5
        ".mov"  = 6
        ".m4a"  = 7
        ".mp3"  = 8
        ".wav"  = 9
        ".ogg"  = 10
    }

    return $candidates |
        Sort-Object @{
            Expression = {
                $ext = $_.Extension.ToLowerInvariant()
                if ($priority.ContainsKey($ext)) { $priority[$ext] } else { 99 }
            }
        }, @{
            Expression = { $_.FullName }
        } |
        Select-Object -First 1
}

$root = Resolve-RepoRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$pipelineScript = Join-Path $root "scripts\Run-MediaKonspektPipeline.ps1"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Не найден venv Python: $python"
}
if (-not (Test-Path -LiteralPath $pipelineScript)) {
    throw "Не найден scripts\Run-MediaKonspektPipeline.ps1"
}

$dataDir = Get-DataDir -PythonExe $python -RepoRoot $root
$folderAbs = Resolve-DataFolder -RawFolder $Folder -DataDir $dataDir

$mdFiles = Get-ChildItem -LiteralPath $folderAbs -Filter "*.md" -File -Recurse:$Recurse |
    Where-Object { $SkipMdNames -notcontains $_.Name.ToLowerInvariant() }

$mediaFiles = Get-ChildItem -LiteralPath $folderAbs -File -Recurse:$Recurse |
    Where-Object { $MediaExtensions -contains $_.Extension.ToLowerInvariant() }

$mediaByStem = @{}
foreach ($media in $mediaFiles) {
    $stem = Get-NormalizedStem $media.FullName
    if (-not $mediaByStem.ContainsKey($stem)) {
        $mediaByStem[$stem] = @()
    }
    $mediaByStem[$stem] += $media
}

$pairs = @()
$skippedKonspekts = @()
$usedMedia = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

foreach ($md in ($mdFiles | Sort-Object FullName)) {
    $stem = Get-NormalizedStem $md.FullName
    $media = Find-MediaForStem `
        -Stem $stem `
        -MediaByStem $mediaByStem `
        -Directory $md.DirectoryName `
        -SameDirectoryOnly ([bool]$Recurse)
    if (-not $media) {
        $skippedKonspekts += $md
        continue
    }
    $usedMedia.Add($media.FullName) | Out-Null
    $pairs += [PSCustomObject]@{
        Konspekt = Get-DataRelativePath -AbsolutePath $md.FullName -DataDir $dataDir
        Media    = $media.FullName
        Stem     = $stem
    }
}

$orphanMedia = $mediaFiles | Where-Object { -not $usedMedia.Contains($_.FullName) }

Write-Host "Папка:      $folderAbs" -ForegroundColor Cyan
Write-Host "DATA_DIR:   $dataDir" -ForegroundColor DarkGray
Write-Host "Конспектов: $($mdFiles.Count)  |  Видео: $($mediaFiles.Count)  |  Пар: $($pairs.Count)" -ForegroundColor Cyan

if ($skippedKonspekts.Count -gt 0) {
    Write-Host ""
    Write-Host "Конспекты без одноимённого видео ($($skippedKonspekts.Count)):" -ForegroundColor Yellow
    foreach ($item in $skippedKonspekts) {
        Write-Host "  - $($item.Name)"
    }
}

if ($orphanMedia.Count -gt 0) {
    Write-Host ""
    Write-Host "Видео без одноимённого конспекта ($($orphanMedia.Count)):" -ForegroundColor Yellow
    foreach ($item in ($orphanMedia | Sort-Object Name)) {
        Write-Host "  - $($item.Name)"
    }
}

if ($pairs.Count -eq 0) {
    Write-Host ""
    Write-Host "Нет пар для обработки." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "Очередь обработки:" -ForegroundColor Green
foreach ($pair in $pairs) {
    Write-Host "  [$($pair.Konspekt)]  ←  $([System.IO.Path]::GetFileName($pair.Media))"
}

if ($InstallAsrExtra -and -not $WhatIfPreference) {
    Write-Host ""
    Write-Host "=== Установка ASR-extra (.[asr]) ===" -ForegroundColor Cyan
    & $python -m pip install -e "$root[asr]"
    if ($LASTEXITCODE -ne 0) {
        throw "Установка ASR-extra завершилась с кодом $LASTEXITCODE"
    }
}

$ok = 0
$failed = @()

for ($i = 0; $i -lt $pairs.Count; $i++) {
    $pair = $pairs[$i]
    $label = "[$($i + 1)/$($pairs.Count)] $($pair.Konspekt)"

    if (-not $PSCmdlet.ShouldProcess($pair.Konspekt, "media pipeline")) {
        continue
    }

    Write-Host ""
    Write-Host "########################################" -ForegroundColor Magenta
    Write-Host $label -ForegroundColor Magenta
    Write-Host "########################################" -ForegroundColor Magenta

    $pipeArgs = @{
        Konspekt = $pair.Konspekt
        Media    = $pair.Media
        GpuIndex = $GpuIndex
        Model    = $Model
        Language = $Language
    }
    if ($Remux) { $pipeArgs.Remux = $true }
    if ($Force) { $pipeArgs.Force = $true }
    if ($SkipAsr) { $pipeArgs.SkipAsr = $true }
    if ($SkipSidecar) { $pipeArgs.SkipSidecar = $true }
    if ($DryRunSidecar) { $pipeArgs.DryRunSidecar = $true }

    try {
        & $pipelineScript @pipeArgs
        if ($LASTEXITCODE -ne 0) {
            throw "exit code $LASTEXITCODE"
        }
        $ok++
    } catch {
        $failed += [PSCustomObject]@{
            Konspekt = $pair.Konspekt
            Media    = $pair.Media
            Error    = $_.Exception.Message
        }
        Write-Host "ОШИБКА: $($pair.Konspekt) — $($_.Exception.Message)" -ForegroundColor Red
        if ($StopOnError) {
            break
        }
    }
}

Write-Host ""
Write-Host "========== Итог ==========" -ForegroundColor Cyan
Write-Host "Успешно: $($ok)/$($pairs.Count)"
if ($failed.Count -gt 0) {
    Write-Host "Ошибки:  $($failed.Count)" -ForegroundColor Red
    foreach ($item in $failed) {
        Write-Host "  - $($item.Konspekt): $($item.Error)" -ForegroundColor Red
    }
    exit 1
}
