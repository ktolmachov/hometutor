# Run-HomeRagIntegrationGate-v1.ps1
# Runs HomeRagIntegrationGate-v1 against the real hometutor application pipeline.
#
# Default model is the current Home RAG benchmark winner:
#   qwopus3.6-35b-a3b-v1-mtp
#   D:\AI\models\gguf\Qwopus3.6-35B-A3B-v1-MTP-Q4_K_S.gguf
#
# Expected endpoints:
#   LLM:    http://127.0.0.1:8080/v1
#   Embed:  http://127.0.0.1:1234/v1
#
# Usage:
#   cd D:\Projects\hometutor
#   pwsh -ExecutionPolicy Bypass -File D:\AI\Run-HomeRagIntegrationGate-v1.ps1 -ResetHome
#
# Faster rerun after index already exists:
#   pwsh -ExecutionPolicy Bypass -File D:\AI\Run-HomeRagIntegrationGate-v1.ps1 -SkipIngest
#
# Preflight only:
#   pwsh -ExecutionPolicy Bypass -File D:\AI\Run-HomeRagIntegrationGate-v1.ps1 -PreflightOnly

[CmdletBinding()]
param(
    [string]$ProjectRoot = "D:\Projects\hometutor",

    [string]$GateScript = "scripts\home_rag_integration_gate_v1.py",
    [string]$CasesPath = "eval_data\home_rag_gate\home_rag_cases_v1.json",

    [string]$LlamaServerExe = "D:\AI\tools\llama.cpp\build-cuda\bin\llama-server.exe",
    [string]$ModelPath = "D:\AI\models\gguf\Qwopus3.6-35B-A3B-v1-MTP-Q4_K_S.gguf",
    [string]$ModelAlias = "qwopus3.6-35b-a3b-v1-mtp",

    [string]$LlmBaseUrl = "http://127.0.0.1:8080/v1",
    [int]$LlmPort = 8080,

    [string]$EmbedBaseUrl = "http://127.0.0.1:1234/v1",
    [string]$EmbedModel = "text-embedding-qwen3-embedding-0.6b",

    [string]$GateHome = "D:\AI\home_rag_gate_v1",
    [string]$ReportDir = "D:\AI\logs",

    [int]$CtxSize = 32768,
    [int]$Parallel = 1,
    [int]$BatchSize = 512,
    [int]$UBatchSize = 128,
    [ValidateSet("f16", "q8_0", "q4_0", "q4_1")]
    [string]$CacheTypeK = "q8_0",
    [ValidateSet("f16", "q8_0", "q4_0", "q4_1")]
    [string]$CacheTypeV = "q8_0",
    [ValidateSet("auto", "on", "off")]
    [string]$FlashAttn = "on",

    [int]$StartupTimeoutSec = 240,
    [int]$EndpointTimeoutSec = 15,
    [int]$GateTimeoutSec = 10,

    [switch]$StopExisting,
    [switch]$StartServer,
    [switch]$KeepServer,
    [switch]$ResetHome,
    [switch]$SkipIngest,
    [switch]$PreflightOnly,
    [switch]$NoModelStart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Get-TimeStamp {
    return (Get-Date).ToString("yyyy-MM-dd_HH-mm-ss")
}

function Get-ProcessIdsOnPort {
    param([Parameter(Mandatory = $true)] [int]$PortNumber)

    $ids = @()
    try {
        $ids = Get-NetTCPConnection -LocalPort $PortNumber -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique
    }
    catch {
        try {
            $lines = netstat -ano -p tcp | Select-String ":$PortNumber\s+.*LISTENING\s+(\d+)"
            foreach ($line in $lines) {
                if ($line.Line -match "LISTENING\s+(\d+)$") {
                    $ids += [int]$Matches[1]
                }
            }
            $ids = $ids | Select-Object -Unique
        }
        catch {
            $ids = @()
        }
    }

    return @($ids)
}

function Stop-ProcessesOnPort {
    param([Parameter(Mandatory = $true)] [int]$PortNumber)

    $ids = @(Get-ProcessIdsOnPort -PortNumber $PortNumber)
    if ($ids.Count -eq 0) {
        Write-Host "No processes listening on TCP port $PortNumber."
        return
    }

    foreach ($processId in $ids) {
        try {
            $p = Get-Process -Id $processId -ErrorAction Stop
            Write-Host "Stopping PID=$processId Name=$($p.ProcessName) on port $PortNumber" -ForegroundColor Yellow
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Start-Sleep -Milliseconds 800
        }
        catch {
            Write-Warning "Could not stop PID=$processId on port ${PortNumber}: $($_.Exception.Message)"
        }
    }
}

function Invoke-JsonGet {
    param(
        [Parameter(Mandatory = $true)] [string]$Url,
        [int]$TimeoutSec = 10
    )

    Invoke-RestMethod -Method Get -Uri $Url -TimeoutSec $TimeoutSec
}

function Test-ModelsEndpoint {
    param(
        [Parameter(Mandatory = $true)] [string]$BaseUrl,
        [Parameter(Mandatory = $true)] [string]$ExpectedModel,
        [int]$TimeoutSec = 10,
        [switch]$RequireExpectedModel
    )

    $url = $BaseUrl.TrimEnd("/") + "/models"
    $payload = Invoke-JsonGet -Url $url -TimeoutSec $TimeoutSec
    $ids = New-Object System.Collections.Generic.List[string]

    foreach ($item in @($payload.data)) {
        if ($null -eq $item) { continue }
        foreach ($name in @("id", "model", "name")) {
            $prop = $item.PSObject.Properties[$name]
            if ($null -ne $prop -and -not [string]::IsNullOrWhiteSpace([string]$prop.Value)) {
                $ids.Add([string]$prop.Value)
            }
        }
    }

    $modelList = @($ids.ToArray() | Select-Object -Unique)
    $contains = $modelList -contains $ExpectedModel

    Write-Host "Endpoint: $url"
    Write-Host "Models:   $($modelList -join ', ')"
    Write-Host "Expected: $ExpectedModel"
    Write-Host "Contains: $contains"

    if ($RequireExpectedModel -and -not $contains) {
        throw "Endpoint $url does not contain expected model '$ExpectedModel'."
    }

    return [pscustomobject]@{
        url = $url
        models = $modelList
        contains_expected = $contains
    }
}

function Start-LlamaServer {
    param(
        [Parameter(Mandatory = $true)] [string]$Exe,
        [Parameter(Mandatory = $true)] [string]$Model,
        [Parameter(Mandatory = $true)] [string]$Alias,
        [Parameter(Mandatory = $true)] [string]$BaseUrl,
        [Parameter(Mandatory = $true)] [string]$LogDir
    )

    if (-not (Test-Path -LiteralPath $Exe)) {
        throw "llama-server.exe not found: $Exe"
    }
    if (-not (Test-Path -LiteralPath $Model)) {
        throw "Model file not found: $Model"
    }

    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

    $stdoutLog = Join-Path $LogDir "llama-server.$Alias.stdout.log"
    $stderrLog = Join-Path $LogDir "llama-server.$Alias.stderr.log"

    $hostName = "127.0.0.1"
    $portNum = [int]($BaseUrl -replace '^https?://[^:]+:(\d+)/.*$', '$1')
    if ($portNum -le 0) { $portNum = $LlmPort }

    $args = @(
        "--model", $Model,
        "--alias", $Alias,
        "--host", $hostName,
        "--port", [string]$portNum,
        "--ctx-size", [string]$CtxSize,
        "--parallel", [string]$Parallel,
        "--batch-size", [string]$BatchSize,
        "--ubatch-size", [string]$UBatchSize,
        "--cache-type-k", $CacheTypeK,
        "--cache-type-v", $CacheTypeV,
        "--flash-attn", $FlashAttn,
        "--metrics"
    )

    # Important: do not force --n-gpu-layers / --tensor-split / --split-mode here.
    # Let llama.cpp AUTO/FIT pick placement. This matched the accepted benchmark run.

    $env:LLAMA_ARG_CHAT_TEMPLATE_KWARGS = '{"enable_thinking":false}'

    Write-Host "Starting llama.cpp server"
    Write-Host "Alias: $Alias"
    Write-Host "Model: $Model"
    Write-Host "Args:  $($args -join ' ')"
    Write-Host "Logs:  $stdoutLog"

    $proc = Start-Process -FilePath $Exe `
        -ArgumentList $args `
        -PassThru `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -WindowStyle Hidden

    return [pscustomobject]@{
        process = $proc
        stdout_log = $stdoutLog
        stderr_log = $stderrLog
    }
}

function Wait-ModelReady {
    param(
        [Parameter(Mandatory = $true)] [string]$BaseUrl,
        [Parameter(Mandatory = $true)] [string]$ExpectedModel,
        [Parameter(Mandatory = $true)] [System.Diagnostics.Process]$Process,
        [int]$TimeoutSec = 240
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $lastError = $null

    while ((Get-Date) -lt $deadline) {
        if ($Process.HasExited) {
            throw "llama-server exited early with code $($Process.ExitCode)"
        }

        try {
            [void](Test-ModelsEndpoint `
                -BaseUrl $BaseUrl `
                -ExpectedModel $ExpectedModel `
                -TimeoutSec 5 `
                -RequireExpectedModel)
            return
        }
        catch {
            $lastError = $_.Exception.Message
            Start-Sleep -Seconds 2
        }
    }

    throw "Model did not become ready in ${TimeoutSec}s. Last error: $lastError"
}

function Test-PythonScriptSyntax {
    param([Parameter(Mandatory = $true)] [string]$PythonExe, [Parameter(Mandatory = $true)] [string]$ScriptPath)

    & $PythonExe -m py_compile $ScriptPath
    if ($LASTEXITCODE -ne 0) {
        throw "Python syntax check failed: $ScriptPath"
    }
}

# ---- main ----

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$gateScriptPath = Join-Path $ProjectRoot $GateScript
$casesFullPath = Join-Path $ProjectRoot $CasesPath
$pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$stamp = Get-TimeStamp
$runLogDir = Join-Path $ReportDir "home_rag_integration_gate_v1_runner_$stamp"

Write-Step "Validate paths"
Write-Host "ProjectRoot: $ProjectRoot"
Write-Host "GateScript:  $gateScriptPath"
Write-Host "CasesPath:   $casesFullPath"
Write-Host "Python:      $pythonExe"
Write-Host "ModelAlias:  $ModelAlias"
Write-Host "GateHome:    $GateHome"
Write-Host "ReportDir:   $ReportDir"

if (-not (Test-Path -LiteralPath $ProjectRoot)) {
    throw "ProjectRoot not found: $ProjectRoot"
}
if (-not (Test-Path -LiteralPath $gateScriptPath)) {
    throw "Gate script not found: $gateScriptPath"
}
if (-not (Test-Path -LiteralPath $casesFullPath)) {
    throw "Cases JSON not found: $casesFullPath"
}
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Project venv python not found: $pythonExe"
}

New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
New-Item -ItemType Directory -Force -Path $runLogDir | Out-Null

Write-Step "Python syntax check"
Test-PythonScriptSyntax -PythonExe $pythonExe -ScriptPath $gateScriptPath
Write-Host "PYTHON_SYNTAX=PASS" -ForegroundColor Green

$serverInfo = $null

try {
    if ($StopExisting) {
        Write-Step "Stop old llama.cpp server on port $LlmPort"
        Stop-ProcessesOnPort -PortNumber $LlmPort
    }

    if (-not $NoModelStart) {
        $portPids = @(Get-ProcessIdsOnPort -PortNumber $LlmPort)
        if ($portPids.Count -gt 0) {
            Write-Host "Port $LlmPort is already in use by PID(s): $($portPids -join ', ')." -ForegroundColor Yellow
            Write-Host "Will reuse existing LLM endpoint: $LlmBaseUrl"
        }
        else {
            if (-not $StartServer) {
                Write-Host "LLM server is not running. Starting it automatically." -ForegroundColor Yellow
            }

            Write-Step "Start recommended LLM"
            $serverInfo = Start-LlamaServer `
                -Exe $LlamaServerExe `
                -Model $ModelPath `
                -Alias $ModelAlias `
                -BaseUrl $LlmBaseUrl `
                -LogDir $runLogDir

            Wait-ModelReady `
                -BaseUrl $LlmBaseUrl `
                -ExpectedModel $ModelAlias `
                -Process $serverInfo.process `
                -TimeoutSec $StartupTimeoutSec

            Write-Host "LLM_READY=PASS" -ForegroundColor Green
        }
    }

    Write-Step "Probe LLM endpoint"
    [void](Test-ModelsEndpoint `
        -BaseUrl $LlmBaseUrl `
        -ExpectedModel $ModelAlias `
        -TimeoutSec $EndpointTimeoutSec `
        -RequireExpectedModel)
    Write-Host "LLM_ENDPOINT=PASS" -ForegroundColor Green

    Write-Step "Probe embedding endpoint"
    [void](Test-ModelsEndpoint `
        -BaseUrl $EmbedBaseUrl `
        -ExpectedModel $EmbedModel `
        -TimeoutSec $EndpointTimeoutSec)
    Write-Host "EMBED_ENDPOINT=PASS" -ForegroundColor Green

    Write-Step "Run HomeRagIntegrationGate-v1"

    $gateArgs = @(
        $gateScriptPath,
        "--cases-path", $casesFullPath,
        "--home", $GateHome,
        "--report-dir", $ReportDir,
        "--llm-base-url", $LlmBaseUrl,
        "--llm-model", $ModelAlias,
        "--embed-base-url", $EmbedBaseUrl,
        "--embed-model", $EmbedModel,
        "--timeout-sec", [string]$GateTimeoutSec
    )

    if ($ResetHome) {
        $gateArgs += "--reset-home"
    }
    if ($SkipIngest) {
        $gateArgs += "--skip-ingest"
    }
    if ($PreflightOnly) {
        $gateArgs += "--preflight-only"
    }

    Push-Location $ProjectRoot
    try {
        Write-Host "Command:"
        Write-Host "$pythonExe $($gateArgs -join ' ')"
        & $pythonExe @gateArgs
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    if ($exitCode -eq 0) {
        Write-Host ""
        Write-Host "HOME_RAG_INTEGRATION_GATE_RUNNER=PASS" -ForegroundColor Green
        exit 0
    }

    Write-Host ""
    Write-Host "HOME_RAG_INTEGRATION_GATE_RUNNER=FAIL exit=$exitCode" -ForegroundColor Red
    exit $exitCode
}
finally {
    if ($serverInfo -and -not $KeepServer) {
        try {
            $proc = $serverInfo.process
            if ($proc -and -not $proc.HasExited) {
                Write-Step "Stop llama.cpp server"
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 2
            }
        }
        catch {
            Write-Warning "Could not stop llama.cpp server: $($_.Exception.Message)"
        }
    }
}
