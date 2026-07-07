<#
.SYNOPSIS
Пакетный прогон media-пайплайна для всех конспектов с видео в подпапке DATA_DIR.

.DESCRIPTION
Сканирует подпапку (напр. D:\AI\app\data\ИИ Агенты\), находит пары
<stem>.md + одноимённое видео (.mp4, .ts, …) и для каждой вызывает
Run-MediaKonspektPipeline.ps1 (remux → GPU ASR → sidecar).

Сопоставление: нормализованный stem (lower-case, подчёркивания/точки → пробелы,
суффикс после " - "/" – "/" — " отсекается). Покрывает расхождения имён вроде
"Модуль_1_..._системы.md" ↔ "Модуль 1. ... системы - Курс «Deep Agents».mp4".
Конспекты без видео и видео без конспекта выводятся в отчёт, но не обрабатываются.

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

    [switch]$StopOnError,

    [switch]$SkipFrontmatter,

    [switch]$NoManifest,

    [string]$ManifestPath = ""
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

    # Stem без расширения, в нижнем регистре — база для регистронезависимого match.
    $name = [System.IO.Path]::GetFileNameWithoutExtension($Path).ToLowerInvariant()
    # Унификация разделителей: подчёркивания и точки → пробелы. Покрывает расхождения
    # вида "Модуль_1_..._системы" (конспект) ↔ "Модуль 1. ... системы" (видео).
    $name = $name -replace '[_.]', ' '
    # Отсечение суффикса-уточнения после " - " / " – " / " — " (напр.
    # "...системы - Курс «Deep Agents»" → "...системы"), чтобы конспект без
    # суффикса сопоставлялся с видео, где суффикс присутствует. Дефисы внутри
    # слов (ai-driven) не задеваются: вокруг них нет пробелов.
    $name = $name -replace '\s+[-\u2013\u2014]\s+.+$', ''
    # Схлопывание повторных пробелов и обрезка краёв.
    return ($name -replace '\s+', ' ').Trim()
}

function Format-Duration {
    param([double]$Seconds)
    $total = [int][math]::Round($Seconds)
    $h = [int][math]::Floor($total / 3600)
    $m = [int][math]::Floor(($total % 3600) / 60)
    $s = $total % 60
    if ($h -gt 0) { return ("{0}:{1:D2}:{2:D2}" -f $h, $m, $s) }
    return ("{0:D2}:{1:D2}" -f $m, $s)
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
$chosenByStem = @{}
$konspektStems = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

foreach ($md in $mdFiles) {
    [void]$konspektStems.Add((Get-NormalizedStem $md.FullName))
}

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
    [void]$usedMedia.Add($media.FullName)
    $chosenByStem[$stem] = $media
    $pairs += [PSCustomObject]@{
        Konspekt = Get-DataRelativePath -AbsolutePath $md.FullName -DataDir $dataDir
        Media    = $media.FullName
        Stem     = $stem
    }
}

# Не выбранные медиа делим на две категории. Дубликат-сиблинг — тот же stem, что у
# конспекта, но выбран другой файл (часто .ts рядом с выбранным .mp4, где .mp4 —
# побочный продукт ремукса). Настоящий сирота — стема нет ни в одном конспекте.
# Прежний код помечал .ts рядом с .mp4 как «видео без конспекта», противореча очереди.
$duplicateMedia = @()
$orphanMedia = @()
foreach ($media in $mediaFiles) {
    if ($usedMedia.Contains($media.FullName)) { continue }
    $stem = Get-NormalizedStem $media.FullName
    if ($konspektStems.Contains($stem)) {
        $duplicateMedia += $media
    } else {
        $orphanMedia += $media
    }
}

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

if ($duplicateMedia.Count -gt 0) {
    Write-Host ""
    Write-Host "Дубликаты медиа (конспект есть, выбран другой файл) ($($duplicateMedia.Count)):" -ForegroundColor DarkYellow
    foreach ($item in ($duplicateMedia | Sort-Object Name)) {
        $stem = Get-NormalizedStem $item.FullName
        $chosen = $chosenByStem[$stem]
        $note = ""
        if ($chosen) {
            if ($item.LastWriteTime -gt $chosen.LastWriteTime) {
                $note = "  ⚠ новее выбранного «$($chosen.Name)» — возможен устаревший ремукс/исходник"
            } else {
                $note = "  (выбран $($chosen.Name))"
            }
        }
        Write-Host "  - $($item.Name)$note"
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

if (-not $WhatIfPreference) {
    try {
        $gpuFree = & nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits --id $GpuIndex 2>$null
        if ($LASTEXITCODE -eq 0 -and $gpuFree) {
            $freeMb = [int]($gpuFree.Trim())
            if ($freeMb -lt 3000) {
                Write-Host "⚠ GPU $GpuIndex свободно ${freeMb} МБ VRAM — large-v3 (~3 ГБ) может не влезть; освободите GPU или укажите -GpuIndex." -ForegroundColor Yellow
            } else {
                Write-Host "GPU ${GpuIndex}: свободно ${freeMb} МБ VRAM." -ForegroundColor DarkGray
            }
        }
    } catch {
        # nvidia-smi недоступен — диагностика не критична.
    }
}

$batchStart = Get-Date
$tempCovDir = Join-Path $env:TEMP "hometutor_media_batch"
$ok = 0
$failed = @()
$results = @()
$totConfident = 0
$totPlaylist = 0.0
$totMedia = 0.0

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

    $pairStart = Get-Date
    $covFile = Join-Path $tempCovDir ("mkbatch_" + [System.IO.Path]::GetRandomFileName() + ".json")

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
    if ($SkipFrontmatter) { $pipeArgs.SkipFrontmatter = $true }
    if (-not $NoManifest -and -not $SkipSidecar) { $pipeArgs.CoverageJson = $covFile }

    $status = "ok"
    $errMsg = ""
    try {
        & $pipelineScript @pipeArgs
        if ($LASTEXITCODE -ne 0) {
            throw "exit code $LASTEXITCODE"
        }
        $ok++
    } catch {
        $status = "failed"
        $errMsg = $_.Exception.Message
        $failed += [PSCustomObject]@{
            Konspekt = $pair.Konspekt
            Media    = $pair.Media
            Error    = $errMsg
        }
        Write-Host "ОШИБКА: $($pair.Konspekt) — $errMsg" -ForegroundColor Red
    }

    $elapsed = (Get-Date) - $pairStart
    $coverage = $null
    if (Test-Path -LiteralPath $covFile) {
        try {
            $coverage = Get-Content -LiteralPath $covFile -Raw -Encoding UTF8 | ConvertFrom-Json
        } catch {
            $coverage = $null
        }
        Remove-Item -LiteralPath $covFile -Force -ErrorAction SilentlyContinue
    }

    if ($status -eq "ok" -and $coverage) {
        $totConfident += [int]$coverage.confident
        $totPlaylist += [double]$coverage.playlist_seconds
        if ($coverage.media_seconds) { $totMedia += [double]$coverage.media_seconds }
        Write-Host ("  ▶ confident {0}/{1} · плейлист {2}" -f $coverage.confident, $coverage.sections, (Format-Duration $coverage.playlist_seconds)) -ForegroundColor Cyan
    }

    $covEntry = $null
    if ($coverage) {
        $covEntry = [ordered]@{
            sections        = $coverage.sections
            with_timestamp  = $coverage.with_timestamp
            anchored        = $coverage.anchored
            interpolated    = $coverage.interpolated
            confident       = $coverage.confident
            playlist_seconds = $coverage.playlist_seconds
            media_seconds   = $coverage.media_seconds
        }
    }
    $results += [PSCustomObject]@{
        Konspekt  = $pair.Konspekt
        Media     = $pair.Media
        Status    = $status
        Error     = $errMsg
        ElapsedSec = [math]::Round($elapsed.TotalSeconds, 1)
        Coverage  = $covEntry
    }

    $done = $i + 1
    $avgSec = ((Get-Date) - $batchStart).TotalSeconds / $done
    $remainSec = ($pairs.Count - $done) * $avgSec
    Write-Host ("  ⏱ {0} прошло, ~{1} осталось ({2}/{3})" -f (Format-Duration $elapsed.TotalSeconds), (Format-Duration $remainSec), $done, $pairs.Count) -ForegroundColor DarkGray

    if ($status -eq "failed" -and $StopOnError) {
        break
    }
}

Write-Host ""
Write-Host "========== Итог ==========" -ForegroundColor Cyan
Write-Host "Успешно: $($ok)/$($pairs.Count)"
if ($ok -gt 0) {
    Write-Host ("Продуктово: confident-разделов {0} · плейлист-готово {1} из {2} лекций" -f $totConfident, (Format-Duration $totPlaylist), (Format-Duration $totMedia)) -ForegroundColor Cyan
}
if ($failed.Count -gt 0) {
    Write-Host "Ошибки:  $($failed.Count)" -ForegroundColor Red
    foreach ($item in $failed) {
        Write-Host "  - $($item.Konspekt): $($item.Error)" -ForegroundColor Red
    }
}

if (-not $NoManifest -and -not $WhatIfPreference) {
    # Манифест — артефакт прогона, не контент: по умолчанию в scratch-каталоге
    # ($env:TEMP), чтобы не подмешивать провенанс в папку лекций (DATA_DIR).
    # -ManifestPath задаёт явное расположение (напр., для автоматизации).
    if (-not $ManifestPath) {
        $manifestPath = Join-Path $tempCovDir "media_konspekt_batch_manifest.json"
    } else {
        $manifestPath = $ManifestPath
    }
    $manifestDir = Split-Path $manifestPath -Parent
    if ($manifestDir -and -not (Test-Path -LiteralPath $manifestDir)) {
        New-Item -ItemType Directory -Path $manifestDir -Force | Out-Null
    }
    $manifest = [ordered]@{
        started_at  = $batchStart.ToString("o")
        finished_at = (Get-Date).ToString("o")
        folder      = $folderAbs
        data_dir    = $dataDir
        gpu_index   = $GpuIndex
        totals      = [ordered]@{
            pairs              = $pairs.Count
            ok                 = $ok
            failed             = $failed.Count
            confident_sections = $totConfident
            playlist_seconds   = [math]::Round($totPlaylist, 2)
            media_seconds      = [math]::Round($totMedia, 2)
        }
        results     = $results
    }
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    Write-Host "Манифест:  $manifestPath" -ForegroundColor DarkGray
}

if ($failed.Count -gt 0) {
    exit 1
}
exit 0
