#requires -Version 5.1
<#
.SYNOPSIS
  Warm retrieval/reranker/query-engine inside a running hometutor API process.

.EXAMPLE
  .\scripts\Warmup-HomeRagRag.ps1

.EXAMPLE
  .\scripts\run_local_stack.ps1 -WarmupRag
#>
param(
    [string] $ApiBase = "http://127.0.0.1:8000",
    [int] $TimeoutSec = 180,
    [switch] $WaitForHealth
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$HealthUrl = "$($ApiBase.TrimEnd('/'))/health"
$AskUrl = "$($ApiBase.TrimEnd('/'))/ask"
$WarmupFile = "урок_1 Введение в концепцию AI-агентов.md"

function Wait-ApiHealth {
    param([int] $MaxWaitSec = 30)
    $waited = 0
    while ($waited -lt $MaxWaitSec) {
        try {
            $health = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 2
            if ($health.status -eq "ok") {
                return
            }
        } catch {
        }
        Start-Sleep -Milliseconds 500
        $waited += 1
    }
    throw "API health check failed at $HealthUrl within ${MaxWaitSec}s"
}

if ($WaitForHealth) {
    Wait-ApiHealth
}

Write-Host "Warming RAG via POST /ask (quality, reranker, query engine)..." -ForegroundColor Yellow

$Payload = @{
    question = "Прогрев retrieval: ответь одним словом ok."
    profile = "quality"
    file_name = $WarmupFile
} | ConvertTo-Json -Depth 4 -Compress

$BodyBytes = [System.Text.Encoding]::UTF8.GetBytes($Payload)
$Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$Response = Invoke-RestMethod `
    -Uri $AskUrl `
    -Method Post `
    -ContentType "application/json; charset=utf-8" `
    -Body $BodyBytes `
    -TimeoutSec $TimeoutSec
$Stopwatch.Stop()

$TotalMs = [math]::Round($Stopwatch.Elapsed.TotalMilliseconds, 0)
$Debug = $Response.debug
$EngineMs = if ($Debug) { $Debug.engine_acquire_ms } else { $null }
$LlmMs = if ($Debug) { $Debug.llm_ms } else { $null }

Write-Host ""
Write-Host "WARMUP_RAG=PASS" -ForegroundColor Green
Write-Host "api_base=$ApiBase"
Write-Host "elapsed_ms=$TotalMs"
if ($null -ne $EngineMs) { Write-Host "engine_acquire_ms=$EngineMs" }
if ($null -ne $LlmMs) { Write-Host "llm_ms=$LlmMs" }
Write-Host "sources=$(@($Response.sources).Count)"
exit 0
