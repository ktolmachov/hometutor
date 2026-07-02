# Run-HomeRagProductBaseline-v1.ps1
# Runs HomeRagProductBaseline-v1 with the fixed accepted local RAG/tutor model.

[CmdletBinding()]
param(
    [string]$ProjectRoot = "D:\Projects\hometutor",
    [switch]$StopExisting,
    [switch]$KeepServer,
    [switch]$ResetHome,
    [switch]$SkipIngest,
    [switch]$PreflightOnly,
    [switch]$NoModelStart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$baseRunner = Join-Path $ProjectRoot "scripts\Run-HomeRagIntegrationGate-v1.ps1"
if (-not (Test-Path -LiteralPath $baseRunner)) {
    throw "Base runner not found: $baseRunner"
}

$argsList = @(
    "-ProjectRoot", $ProjectRoot,
    "-GateScript", "scripts\home_rag_product_baseline_v1.py",
    "-CasesPath", "eval_data\home_rag_product_baseline\home_rag_product_baseline_v1.json",
    "-GateHome", "D:\AI\home_rag_product_baseline_v1",
    "-ReportDir", "D:\AI\logs",
    "-ModelAlias", "qwopus3.6-35b-a3b-v1-mtp",
    "-ModelPath", "D:\AI\models\gguf\Qwopus3.6-35B-A3B-v1-MTP-Q4_K_S.gguf",
    "-GateTimeoutSec", "10"
)

if ($StopExisting) { $argsList += "-StopExisting" }
if ($KeepServer) { $argsList += "-KeepServer" }
if ($ResetHome) { $argsList += "-ResetHome" }
if ($SkipIngest) { $argsList += "-SkipIngest" }
if ($PreflightOnly) { $argsList += "-PreflightOnly" }
if ($NoModelStart) { $argsList += "-NoModelStart" }

& pwsh -ExecutionPolicy Bypass -File $baseRunner @argsList
exit $LASTEXITCODE
