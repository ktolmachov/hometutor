<#
.SYNOPSIS
Шаблон полного offline-пайплайна для нового видео: remux (опц.) → GPU ASR → media sidecar.

.DESCRIPTION
Связывает три шага подготовки мультимодального конспекта:
  1) remux .ts → .mp4 (автоматически для .ts/.mts, иначе -Remux)
  2) транскрибация на GPU (large-v3; НЕ large-v3-turbo — хуже выравнивание sidecar)
  3) сборка <konspekt>.media.json (таймкоды разделов)

Конспект и медиа должны лежать в DATA_DIR (по умолчанию D:\AI\app\data).

.PARAMETER Konspekt
Data-relative путь к конспекту, напр. "ИИ Агенты/урок_3_название.md"

.PARAMETER Media
Абсолютный путь к видео/аудио внутри DATA_DIR (.mp4, .ts, .mkv …).

.PARAMETER Video
Data-relative путь к playable .mp4 для sidecar. По умолчанию выводится из Media
(для .ts берётся одноимённый .mp4 после remux).

.PARAMETER GpuIndex
Индекс GPU для CUDA_VISIBLE_DEVICES. На двух 5070 Ti обычно 1 = вторая карта.

.EXAMPLE
# Новый урок (.mp4 уже в DATA_DIR)
.\scripts\Run-MediaKonspektPipeline.ps1 `
  -Konspekt "ИИ Агенты/урок_3_мой_урок.md" `
  -Media "D:\AI\app\data\ИИ Агенты\урок_3_мой_урок.mp4" `
  -GpuIndex 1

.EXAMPLE
# Запись в .ts + принудительная пере-транскрибация
.\scripts\Run-MediaKonspektPipeline.ps1 `
  -Konspekt "ИИ Агенты/урок_3_мой_урок.md" `
  -Media "D:\AI\app\data\ИИ Агенты\урок_3_мой_урок.ts" `
  -GpuIndex 1 -Force

.EXAMPLE
# Первый запуск на машине — установить ASR-extra (cuBLAS + faster-whisper)
.\scripts\Run-MediaKonspektPipeline.ps1 -InstallAsrExtra `
  -Konspekt "ИИ Агенты/урок_3_мой_урок.md" `
  -Media "D:\AI\app\data\ИИ Агенты\урок_3_мой_урок.mp4"

.EXAMPLE
# Только пересобрать sidecar (ASR уже есть)
.\scripts\Run-MediaKonspektPipeline.ps1 `
  -Konspekt "ИИ Агенты/урок_3_мой_урок.md" `
  -Media "D:\AI\app\data\ИИ Агенты\урок_3_мой_урок.mp4" `
  -SkipAsr

.EXAMPLE
# Превью покрытия sidecar без записи
.\scripts\Run-MediaKonspektPipeline.ps1 `
  -Konspekt "ИИ Агенты/урок_3_мой_урок.md" `
  -Media "D:\AI\app\data\ИИ Агенты\урок_3_мой_урок.mp4" `
  -SkipAsr -DryRunSidecar
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Konspekt,

    [Parameter(Mandatory = $true)]
    [string]$Media,

    [string]$Video = "",

    [int]$GpuIndex = 1,

    # large-v3-turbo быстрее, но даёт мелкие сегменты и хуже выравнивание sidecar.
    [string]$Model = "large-v3",

    [string]$Language = "auto",

    [switch]$Remux,

    [switch]$Force,

    [switch]$InstallAsrExtra,

    [switch]$SkipAsr,

    [switch]$SkipSidecar,

    [switch]$DryRunSidecar,

    [string]$CoverageJson = "",

    [switch]$SkipFrontmatter
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Get-DataDir {
    param([string]$PythonExe, [string]$RepoRoot)

    $repoForPy = $RepoRoot.Replace("'", "''")
    $code = "import sys; sys.path.insert(0, r'$repoForPy'); from app.path_safety import resolve_data_relative_path; print(resolve_data_relative_path('.').resolve())"
    return (& $PythonExe -c $code).Trim()
}

function Get-DataRelativePath {
    param([string]$AbsolutePath, [string]$DataDir)

    $abs = [System.IO.Path]::GetFullPath($AbsolutePath)
    $root = [System.IO.Path]::GetFullPath($DataDir).TrimEnd('\', '/')
    $inside = $abs.Equals($root, [System.StringComparison]::OrdinalIgnoreCase) -or
        $abs.StartsWith("$root\", [System.StringComparison]::OrdinalIgnoreCase)
    if (-not $inside) {
        throw "Путь вне DATA_DIR: $abs (ожидался префикс $root)"
    }
    $rel = $abs.Substring($root.Length).TrimStart('\', '/')
    return ($rel -replace '\\', '/')
}

function Invoke-Step {
    param(
        [string]$Title,
        [scriptblock]$Action
    )

    Write-Host ""
    Write-Host "=== $Title ===" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "Шаг завершился с кодом ${LASTEXITCODE}: $Title"
    }
}

$root = Resolve-RepoRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$asrScript = Join-Path $root "scripts\Run-ASRTranscribeCuda.ps1"
$sidecarScript = Join-Path $root "scripts\build_media_sidecar.py"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Не найден venv Python: $python"
}

if ($InstallAsrExtra) {
    Invoke-Step "Установка ASR-extra (.[asr], cuBLAS + faster-whisper)" {
        & $python -m pip install -e "$root[asr]"
    }
}

$dataDir = Get-DataDir -PythonExe $python -RepoRoot $root
$mediaAbs = (Resolve-Path -LiteralPath $Media).Path
$konspektAbs = Join-Path $dataDir ($Konspekt -replace '/', '\')

if (-not (Test-Path -LiteralPath $konspektAbs)) {
    throw "Конспект не найден: $konspektAbs"
}
if (-not (Test-Path -LiteralPath $mediaAbs)) {
    throw "Медиа не найдено: $mediaAbs"
}

$mediaExt = [System.IO.Path]::GetExtension($mediaAbs).ToLowerInvariant()
$needsRemux = $Remux -or $mediaExt -in @(".ts", ".mts", ".m2ts")
$videoWasExplicit = [bool]$Video
$playableAbs = if ($needsRemux) {
    [System.IO.Path]::ChangeExtension($mediaAbs, ".mp4")
} else {
    $mediaAbs
}

if (-not $Video) {
    $Video = Get-DataRelativePath -AbsolutePath $playableAbs -DataDir $dataDir
}

if (-not $SkipAsr) {
    $asrArgs = @{
        Media       = $mediaAbs
        GpuIndex    = $GpuIndex
        Model       = $Model
        Language    = $Language
    }
    if ($needsRemux) { $asrArgs.Remux = $true }
    if ($Force) { $asrArgs.Force = $true }

    Invoke-Step "GPU ASR ($Model, GPU $GpuIndex)" {
        & $asrScript @asrArgs
    }
} else {
    Write-Host "Пропуск ASR (-SkipAsr)." -ForegroundColor DarkGray
}

if ($needsRemux -and -not $videoWasExplicit -and -not (Test-Path -LiteralPath $playableAbs)) {
    Write-Host "Ремукс не создал .mp4; sidecar будет привязан к исходному контейнеру." -ForegroundColor Yellow
    $playableAbs = $mediaAbs
    $Video = Get-DataRelativePath -AbsolutePath $playableAbs -DataDir $dataDir
}

if (-not $SkipSidecar) {
    $sidecarArgs = @(
        $sidecarScript,
        $Konspekt,
        "--video", $Video
    )
    if ($DryRunSidecar) {
        $sidecarArgs += "--dry-run"
    }
    if ($CoverageJson) {
        $sidecarArgs += @("--coverage-json", $CoverageJson)
    }
    if ($SkipFrontmatter) {
        $sidecarArgs += "--no-frontmatter"
    }

    Invoke-Step "Media sidecar ($Konspekt → $Video)" {
        & $python @sidecarArgs
    }
} else {
    Write-Host "Пропуск sidecar (-SkipSidecar)." -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Готово." -ForegroundColor Green
Write-Host "  Конспект:  $Konspekt"
Write-Host "  Видео:     $Video"
Write-Host "  Сегменты:  $([System.IO.Path]::ChangeExtension($playableAbs, '.segments.json'))"
Write-Host "  Sidecar:   $([System.IO.Path]::ChangeExtension($konspektAbs, '.media.json'))"

exit 0
