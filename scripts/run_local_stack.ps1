#requires -Version 5.1
<#
.SYNOPSIS
  Запуск API (uvicorn :8000), затем Streamlit UI (:8501) с поддержкой локального LLM (LM Studio).

  Предварительно запустите LM Studio (http://127.0.0.1:1234) и загрузите модель.
  Скрипт проверит соединение и настроит SSR (Smart Study Router) для использования локальной модели.

.EXAMPLE
  # Первый запуск:
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  pip install -r requirements.txt
  copy .env.example .env
  # Отредактируйте .env: SSR_LLM_MODEL=<id вашей модели>
  python scripts\bootstrap.py

  # Запуск стека (LM Studio должна быть запущена):
  .\scripts\run_local_stack.ps1

  # При повторном запуске (скипим pip install):
  .\scripts\run_local_stack.ps1 -SkipPip

  # С прогревом RAG перед Streamlit:
  .\scripts\run_local_stack.ps1 -WarmupRag

.NOTES
  Для локального LLM требуется:
  - LM Studio запущена на http://127.0.0.1:1234
  - Модель загружена в LM Studio
  - LLM_API_BASE=http://127.0.0.1:1234/v1 в .env для LLM_MODEL / QUIZ_LLM_MODEL
  - SSR_LLM_API_BASE= в .env, если SSR должен использовать тот же LLM_API_BASE
  - SSR_LLM_MODEL=<id модели> в .env (опционально; по умолчанию LLM_MODEL)
#>
param(
    [switch] $SkipPip,
    [switch] $WarmupRag
)

# Вывод кириллицы в консоли + корректная кодировка дочерних процессов (Windows PowerShell 5.x).
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [Console]::OutputEncoding
} catch {
}

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

# UV-стиль: venv ссылается на <repo>\.python\python.exe. После переноса папки pyvenv.cfg
# часто остаётся со старым диском/путём — .venv\Scripts\python.exe падает с «No Python at …».
function Repair-UvStylePyvenvIfBroken {
    param([string]$RepoRoot)
    $cfgPath = Join-Path $RepoRoot ".venv\pyvenv.cfg"
    $uvExe = Join-Path $RepoRoot ".python\python.exe"
    if (-not (Test-Path -LiteralPath $cfgPath)) { return }
    if (-not (Test-Path -LiteralPath $uvExe)) { return }
    $lines = @(Get-Content -LiteralPath $cfgPath)
    $exeLine = $lines | Where-Object { $_ -match '^\s*executable\s*=' } | Select-Object -First 1
    if (-not $exeLine) { return }
    if ($exeLine -match 'executable\s*=\s*(.+)') {
        $oldExe = $Matches[1].Trim().Trim('"')
        if (Test-Path -LiteralPath $oldExe) { return }
    }
    $uvRoot = Join-Path $RepoRoot ".python"
    $venvPath = Join-Path $RepoRoot ".venv"
    $newLines = foreach ($line in $lines) {
        if ($line -match '^\s*home\s*=') { "home = $uvRoot" }
        elseif ($line -match '^\s*executable\s*=') { "executable = $uvExe" }
        elseif ($line -match '^\s*command\s*=') { "command = $uvExe -m venv $venvPath" }
        else { $line }
    }
    $enc = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllLines($cfgPath, $newLines, $enc)
    Write-Host "Обновлён .venv\pyvenv.cfg: base Python → $uvExe (репозиторий перенесён)." -ForegroundColor Yellow
}

Repair-UvStylePyvenvIfBroken -RepoRoot $Root

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Host "Не найден интерпретатор: $Py" -ForegroundColor Red
    Write-Host "Создайте окружение: python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

# Clear Python env vars that can leak a system/foreign interpreter into the venv.
# Without this, PYTHONHOME/PYTHONPATH from another installation (e.g. a different
# Windows user) cause "SRE module mismatch" / wrong stdlib errors.
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null

if (-not $SkipPip) {
    Write-Host "pip install -r requirements.txt ..." -ForegroundColor Cyan
    & $Py -m pip install -r (Join-Path $Root "requirements.txt")
}

Write-Host "scripts/bootstrap.py ..." -ForegroundColor Cyan
& $Py (Join-Path $Root "scripts\bootstrap.py")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

# ── Pre-flight: Local LLM stack checks ─────────────────────────────────────────

Write-Host "`n🔍 Pre-flight checks for local LLM integration..." -ForegroundColor Cyan

$envPath2 = Join-Path $Root ".env"
$configEnvPath = Join-Path $Root "config.env"

function Remove-DotEnvInlineComment {
    param([string]$Value)
    if ($null -eq $Value) { return "" }
    $inSingle = $false
    $inDouble = $false
    for ($i = 0; $i -lt $Value.Length; $i++) {
        $ch = $Value[$i]
        if ($ch -eq "'" -and -not $inDouble) {
            $inSingle = -not $inSingle
        } elseif ($ch -eq '"' -and -not $inSingle) {
            $inDouble = -not $inDouble
        } elseif ($ch -eq "#" -and -not $inSingle -and -not $inDouble) {
            if ($i -eq 0 -or [char]::IsWhiteSpace($Value[$i - 1])) {
                return $Value.Substring(0, $i).Trim()
            }
        }
    }
    return $Value.Trim()
}

function Get-DotEnvValue {
    param(
        [string]$Path,
        [string]$Name
    )
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match "^\s*$([regex]::Escape($Name))\s*=\s*(.*)$") {
            $raw = Remove-DotEnvInlineComment -Value $Matches[1]
            return $raw.Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

function Get-RuntimeEnvValue {
    param([string]$Name)
    $fromEnv = Get-DotEnvValue -Path $envPath2 -Name $Name
    if ($null -ne $fromEnv) { return $fromEnv }
    return Get-DotEnvValue -Path $configEnvPath -Name $Name
}

function Get-OpenAIModelsUrl {
    param([string]$BaseUrl)
    $base = ($BaseUrl.Trim()).TrimEnd("/")
    if ($base -match "/v1$") {
        return "$base/models"
    }
    return "$base/v1/models"
}

$llmBase = Get-RuntimeEnvValue -Name "LLM_API_BASE"
if ([string]::IsNullOrWhiteSpace($llmBase)) {
    $llmBase = "http://127.0.0.1:1234/v1"
}

$ssrRawBase = Get-RuntimeEnvValue -Name "SSR_LLM_API_BASE"
if ($null -eq $ssrRawBase) {
    $ssrBase = "http://127.0.0.1:1234"
    $ssrUsesMain = $false
} elseif ([string]::IsNullOrWhiteSpace($ssrRawBase)) {
    $ssrBase = $llmBase
    $ssrUsesMain = $true
} else {
    $ssrBase = $ssrRawBase
    $ssrUsesMain = $false
}

$llmModel = Get-RuntimeEnvValue -Name "LLM_MODEL"
$quizModel = Get-RuntimeEnvValue -Name "QUIZ_LLM_MODEL"
$ssrModel = Get-RuntimeEnvValue -Name "SSR_LLM_MODEL"
if ([string]::IsNullOrWhiteSpace($ssrModel)) { $ssrModel = $llmModel }

# Check if LM Studio is reachable
$localLlmBase = $llmBase -match '127\.0\.0\.1|localhost'
$localSsrBase = $ssrBase -match '127\.0\.0\.1|localhost'
$probeBase = if ($localSsrBase) { $ssrBase } elseif ($localLlmBase) { $llmBase } else { $null }

if ($probeBase) {
    $probeUrl = Get-OpenAIModelsUrl -BaseUrl $probeBase
    try {
        $probe = Invoke-WebRequest -Uri $probeUrl -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        Write-Host "✓ Local OpenAI-compatible LLM detected on $probeBase" -ForegroundColor Green
        try {
            $models = $probe.Content | ConvertFrom-Json
            if ($models.data) {
                Write-Host "  Models loaded: $($models.data.Count)" -ForegroundColor Green
                foreach ($m in $models.data | Select-Object -First 3) {
                    Write-Host "    • $($m.id)" -ForegroundColor DarkGreen
                }
            }
        } catch {
            Write-Host "  (couldn't parse model list)" -ForegroundColor DarkYellow
        }
    } catch {
        Write-Host "⚠ Local OpenAI-compatible LLM not responding on $probeBase" -ForegroundColor Yellow
        Write-Host "  → Start LM Studio and load a model, or point LLM_API_BASE/SSR_LLM_API_BASE to a reachable endpoint" -ForegroundColor DarkYellow
    }
} else {
    Write-Host "ℹ LLM_API_BASE is not loopback → skipping local LM Studio probe ($llmBase)" -ForegroundColor Cyan
}

# Check .env for SSR settings
$localSsrEnabled = $false
Write-Host "✓ .env: LLM_API_BASE → $llmBase" -ForegroundColor Green
if ($llmModel) {
    Write-Host "  LLM_MODEL: $llmModel" -ForegroundColor Green
}
if ($quizModel) {
    Write-Host "  QUIZ_LLM_MODEL: $quizModel" -ForegroundColor Green
} else {
    Write-Host "  QUIZ_LLM_MODEL not set → will use LLM_MODEL" -ForegroundColor DarkGreen
}

if ($ssrUsesMain) {
    Write-Host "✓ .env: SSR_LLM_API_BASE= (empty) → shares LLM_API_BASE ($llmBase)" -ForegroundColor Green
    $localSsrEnabled = $localLlmBase
} else {
    if ($localSsrBase) {
        Write-Host "✓ .env: SSR configured for local endpoint → $ssrBase" -ForegroundColor Green
        $localSsrEnabled = $true
    } else {
        Write-Host "✓ .env: SSR_LLM_API_BASE → $ssrBase" -ForegroundColor Green
    }
}
if ($ssrModel) {
    Write-Host "  SSR effective model: $ssrModel" -ForegroundColor Green
} else {
    Write-Host "  ⚠ SSR effective model is empty; set LLM_MODEL or SSR_LLM_MODEL" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "═════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  LOCAL LLM STACK — FEATURES ENABLED" -ForegroundColor Cyan
Write-Host "═════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
if ($localSsrEnabled) {
    Write-Host "  ✓ Streaming explanations (tokens appear live)" -ForegroundColor Green
    Write-Host "  ✓ Quality feedback widget (👍/👎)" -ForegroundColor Green
    Write-Host "  ✓ Background pre-generation (warm cache)" -ForegroundColor Green
    Write-Host "  ✓ Semantic caching (hit rate depends on workload)" -ForegroundColor Green
    Write-Host "  ✓ Health probe at startup" -ForegroundColor Green
    Write-Host "  ✓ Circuit breaker (resilience)" -ForegroundColor Green
    Write-Host "  → Dashboard: http://127.0.0.1:8501/feedback_insights" -ForegroundColor Green
} else {
    Write-Host "  ✓ Main chat/quiz use configured LLM_API_BASE" -ForegroundColor Green
    Write-Host "  → Configure SSR_LLM_API_BASE to a loopback endpoint to enable local SSR diagnostics" -ForegroundColor Yellow
}
Write-Host "═════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

$uvicornArgs = @(
    "-m", "uvicorn", "app.api:app",
    "--host", "127.0.0.1",
    "--port", "8000"
)
Write-Host "Запуск API (uvicorn) на http://127.0.0.1:8000 ..." -ForegroundColor Cyan
$backend = Start-Process -FilePath $Py -ArgumentList $uvicornArgs `
    -WorkingDirectory $Root -PassThru -NoNewWindow

try {
    # Wait for uvicorn to accept connections (up to 30 s) instead of a fixed sleep.
    # This eliminates the race condition where Streamlit hit port 8000 before FastAPI
    # finished initializing the Chroma index (~9 s on a typical cold start).
    $maxWaitSec = 30
    $waited = 0
    $apiReady = $false
    Write-Host "  Waiting for API on port 8000..." -ForegroundColor DarkCyan -NoNewline
    while ($waited -lt $maxWaitSec) {
        if ($backend.HasExited) {
            Write-Host " [FAILED]" -ForegroundColor Red
            Write-Error "uvicorn завершился с кодом $($backend.ExitCode). Проверьте порт 8000 и логи выше."
            exit $backend.ExitCode
        }
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect('127.0.0.1', 8000)
            $tcp.Close()
            $apiReady = $true
            break
        } catch {
            Start-Sleep -Milliseconds 500
            $waited += 1
        }
    }
    if (-not $apiReady) {
        Write-Host " [TIMEOUT]" -ForegroundColor Red
        throw "API did not respond on port 8000 within ${maxWaitSec}s. Streamlit launch aborted."
    } else {
        Write-Host " ready (${waited}x500ms)" -ForegroundColor Green
    }

    if ($WarmupRag) {
        Write-Host "`nПрогрев RAG (reranker + query engine в процессе API, ~10–15 s cold)..." -ForegroundColor Cyan
        & (Join-Path $Root "scripts\Warmup-HomeRagRag.ps1") -ApiBase "http://127.0.0.1:8000"
        if ($LASTEXITCODE -ne 0) {
            throw "Warmup-HomeRagRag.ps1 failed with exit code $LASTEXITCODE"
        }
    }

    Write-Host "`n📊 Local LLM Diagnostics (run in another terminal):" -ForegroundColor Cyan
    Write-Host "  Health probe:" -ForegroundColor DarkCyan
    Write-Host "    & .\.venv\Scripts\python.exe -c `"from app.llm_local_health import probe_local_llm; import json; print(json.dumps(probe_local_llm('$ssrBase', '$ssrModel'), indent=2))`"" -ForegroundColor DarkGray
    Write-Host "  Error triage:" -ForegroundColor DarkCyan
    Write-Host "    & .\.venv\Scripts\python.exe scripts\llm_errors_today.py --last 1" -ForegroundColor DarkGray
    Write-Host "  SSR feedback summary:" -ForegroundColor DarkCyan
    Write-Host "    & .\.venv\Scripts\python.exe scripts\ssr_feedback_summary.py" -ForegroundColor DarkGray
    Write-Host "  Circuit breaker state:" -ForegroundColor DarkCyan
    Write-Host "    & .\.venv\Scripts\python.exe -c `"from app.llm_local_circuit import snapshot; import json; print(json.dumps(snapshot(), indent=2))`"" -ForegroundColor DarkGray
    Write-Host ""

    Write-Host "Запуск Streamlit на http://127.0.0.1:8501 (останов: Ctrl+C) ..." -ForegroundColor Cyan
    Write-Host "  Feedback dashboard: http://127.0.0.1:8501/feedback_insights" -ForegroundColor Green
    Write-Host ""
    $streamlitArgs = @(
        "-m", "streamlit", "run", (Join-Path $Root "app\ui\main.py"),
        "--server.address", "127.0.0.1",
        "--server.port", "8501",
        "--browser.gatherUsageStats", "false"
    )
    & $Py @streamlitArgs
} finally {
    if ($backend -and -not $backend.HasExited) {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
}
