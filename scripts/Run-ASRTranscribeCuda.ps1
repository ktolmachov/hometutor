<# 
.SYNOPSIS
Prepare CUDA PATH for faster-whisper/CTranslate2 and run video transcription on GPU.

.EXAMPLE
.\scripts\Run-ASRTranscribeCuda.ps1 `
  -Media "D:\AI\app\data\ИИ Агенты\урок_2_как_агент_думает_и_действует.mp4" `
  -GpuIndex 1

.EXAMPLE
.\scripts\Run-ASRTranscribeCuda.ps1 `
  -Media "D:\AI\app\data\ИИ Агенты\урок_2_как_агент_думает_и_действует.ts" `
  -GpuIndex 1 -Remux
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Media,

    [string]$Model = "large-v3",

    [string]$Language = "auto",

    [int]$BeamSize = 5,

    # 0 = first visible GPU, 1 = second visible GPU, etc.
    [int]$GpuIndex = 0,

    # Example: "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin"
    [string]$CudaBin = "",

    [string]$ImportToData = "",

    [switch]$Remux,

    [switch]$Force,

    [switch]$InstallAsrExtra,

    # Persist CUDA bin to the user PATH. By default PATH is changed only for this process.
    [switch]$PersistUserPath
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Find-Cuda12Bin {
    param([string]$Preferred)

    if ($Preferred) {
        if (Test-Path -LiteralPath (Join-Path $Preferred "cublas64_12.dll")) {
            return (Resolve-Path -LiteralPath $Preferred).Path
        }
        throw "CudaBin задан, но cublas64_12.dll там не найден: $Preferred"
    }

    $candidates = New-Object System.Collections.Generic.List[string]

    foreach ($name in "CUDA_PATH", "CUDA_PATH_V12_0", "CUDA_PATH_V12_1", "CUDA_PATH_V12_2", "CUDA_PATH_V12_3", "CUDA_PATH_V12_4", "CUDA_PATH_V12_5", "CUDA_PATH_V12_6", "CUDA_PATH_V12_8") {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value) {
            $candidates.Add((Join-Path $value "bin"))
        }
    }

    $toolkitRoot = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"
    if (Test-Path -LiteralPath $toolkitRoot) {
        Get-ChildItem -LiteralPath $toolkitRoot -Directory -Filter "v12.*" |
            Sort-Object Name -Descending |
            ForEach-Object { $candidates.Add((Join-Path $_.FullName "bin")) }
    }

    foreach ($pathPart in ($env:PATH -split ";")) {
        if ($pathPart -and (Test-Path -LiteralPath (Join-Path $pathPart "cublas64_12.dll"))) {
            $candidates.Add($pathPart)
        }
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath (Join-Path $candidate "cublas64_12.dll"))) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    return $null
}

function Add-ToProcessPath {
    param([string]$PathToAdd)

    $parts = @($env:PATH -split ";" | Where-Object { $_ })
    if ($parts -notcontains $PathToAdd) {
        $env:PATH = "$PathToAdd;$env:PATH"
    }
}

function Add-ToUserPath {
    param([string]$PathToAdd)

    $current = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @($current -split ";" | Where-Object { $_ })
    if ($parts -contains $PathToAdd) {
        Write-Host "User PATH уже содержит CUDA bin." -ForegroundColor DarkGray
        return
    }
    [Environment]::SetEnvironmentVariable("Path", "$PathToAdd;$current", "User")
    Write-Host "CUDA bin добавлен в User PATH. Новые терминалы увидят это автоматически." -ForegroundColor Yellow
}

function Test-DllVisible {
    param([string]$DllName)

    foreach ($pathPart in ($env:PATH -split ";")) {
        if ($pathPart -and (Test-Path -LiteralPath (Join-Path $pathPart $DllName))) {
            return $true
        }
    }
    return $false
}

$root = Resolve-RepoRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$transcribe = Join-Path $root "scripts\transcribe_media.py"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Не найден venv Python: $python"
}
if (-not (Test-Path -LiteralPath $transcribe)) {
    throw "Не найден scripts\transcribe_media.py"
}

Write-Host "Проверяю NVIDIA GPU..." -ForegroundColor Cyan
try {
    & nvidia-smi
} catch {
    throw "nvidia-smi не найден или NVIDIA driver недоступен. Проверьте драйвер NVIDIA."
}

$cudaBinResolved = Find-Cuda12Bin -Preferred $CudaBin
if (-not $cudaBinResolved) {
    Write-Host ""
    Write-Host "Не найден cublas64_12.dll в PATH и стандартных CUDA 12 каталогах." -ForegroundColor Red
    Write-Host "Установите CUDA Toolkit/Runtime 12.x и cuDNN для CUDA 12.x, затем повторите запуск." -ForegroundColor Yellow
    Write-Host "После установки должно сработать:" -ForegroundColor Yellow
    Write-Host "  where.exe cublas64_12.dll" -ForegroundColor Yellow
    exit 2
}

Add-ToProcessPath -PathToAdd $cudaBinResolved
Write-Host "CUDA bin для текущего процесса: $cudaBinResolved" -ForegroundColor Green

if ($PersistUserPath) {
    Add-ToUserPath -PathToAdd $cudaBinResolved
}

if (-not (Test-DllVisible "cublas64_12.dll")) {
    throw "cublas64_12.dll всё ещё не виден после обновления PATH."
}

if (-not (Test-DllVisible "cudnn64_8.dll")) {
    Write-Host "Предупреждение: cudnn64_8.dll не найден в PATH. CTranslate2 speech recognition может потребовать cuDNN 8 for CUDA 12.x." -ForegroundColor Yellow
}

if ($InstallAsrExtra) {
    Write-Host "Устанавливаю optional ASR extra..." -ForegroundColor Cyan
    & $python -m pip install -e "$root[asr]"
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$env:CUDA_VISIBLE_DEVICES = [string]$GpuIndex
Write-Host "CUDA_VISIBLE_DEVICES=$env:CUDA_VISIBLE_DEVICES" -ForegroundColor Green

$argsList = @(
    $transcribe,
    $Media,
    "--device", "cuda",
    "--model", $Model,
    "--language", $Language,
    "--beam-size", [string]$BeamSize
)

if ($ImportToData) {
    $argsList += @("--import-to-data", $ImportToData)
}
if ($Remux) {
    $argsList += "--remux"
}
if ($Force) {
    $argsList += "--force"
}

Write-Host "Запускаю ASR на GPU..." -ForegroundColor Cyan
& $python @argsList
exit $LASTEXITCODE
