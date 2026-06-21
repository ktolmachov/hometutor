#requires -Version 5.1
<#
.SYNOPSIS
  One-command localhost launcher for home-rag.

.DESCRIPTION
  Runs a readiness gate first, then delegates to scripts\run_local_stack.ps1.
  Use -Demo when you want the checks to tolerate a demo-data-only setup.

.EXAMPLE
  .\scripts\local_start.ps1 -SkipPip

.EXAMPLE
  .\scripts\local_start.ps1 -Demo -ProbeModels
#>
param(
    [switch] $Demo,
    [switch] $SkipPip,
    [switch] $ProbeModels,
    [switch] $AllowRunning
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

# Data root: HOME_RAG_HOME env or default D:\AI\app
$DataRoot = if ($env:HOME_RAG_HOME) { $env:HOME_RAG_HOME } else { "D:\AI\app" }
if (-not (Test-Path $DataRoot)) { Write-Host "[!] Data root not found: $DataRoot" -ForegroundColor Yellow }
$env:HOME_RAG_HOME = $DataRoot

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Py)) {
    Write-Host "Не найден $Py" -ForegroundColor Red
    Write-Host "Создайте окружение: python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

$readinessArgs = @(
    (Join-Path $Root "scripts\local_readiness.py"),
    "--root", $Root
)

if ($Demo) {
    $readinessArgs += @("--mode", "demo")
}
if ($ProbeModels) {
    $readinessArgs += @("--probe-models")
}
if ($AllowRunning) {
    $readinessArgs += @("--allow-running")
}

Write-Host "Localhost readiness gate..." -ForegroundColor Cyan
& $Py @readinessArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Запуск остановлен: readiness gate нашёл blocker." -ForegroundColor Red
    Write-Host "Исправьте FAIL-пункты и повторите команду." -ForegroundColor Yellow
    exit $LASTEXITCODE
}

$stackArgs = @{}
if ($SkipPip) {
    $stackArgs.SkipPip = $true
}

Write-Host ""
Write-Host "Readiness OK. Starting localhost stack..." -ForegroundColor Green
& (Join-Path $Root "scripts\run_local_stack.ps1") @stackArgs
