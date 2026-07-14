param(
    [string]$RepoRoot = "D:\Projects\hometutor-studio",
    [string]$Run = "",
    [string[]]$ScenarioId = @(),
    [switch]$FastGifs,
    [switch]$SkipCapture,
    [switch]$SkipGifs,
    [switch]$DryRun,
    [switch]$ContinueOnError
)

. "$PSScriptRoot\common.ps1"

$repo = Resolve-RepoRoot $RepoRoot
$python = Get-StudioPython $repo
$runName = Get-RunName $Run
$envMap = @{ DEMO_SHOT_RUN = $runName; PYTHONIOENCODING = "utf-8" }

$args = @("scripts\demo_workflow.py", "--run", $runName)
foreach ($sid in $ScenarioId) {
    if ($sid -notmatch '^scenario_\d{2}$') {
        throw "ScenarioId must look like scenario_21, got: $sid"
    }
    $args += @("--scenario-id", $sid)
}
if ($DryRun) { $args += "--dry-run" }
$args += "full"
if ($SkipCapture) { $args += "--skip-capture" }
if ($SkipGifs) { $args += "--skip-gifs" }
if ($FastGifs) { $args += "--fast" }
if ($ContinueOnError) { $args += "--continue-on-error" }

Write-Host "RUN: $runName"
Write-Host "SHOTS: doc\screenshots\$runName"
if ($ScenarioId.Count -gt 0) {
    Write-Host "Scenarios: $($ScenarioId -join ', ')"
} else {
    Write-Host "Scenarios: all"
}

Invoke-Checked -FilePath $python -Arguments $args -WorkingDirectory $repo -Environment $envMap

Write-Host ""
Write-Host "Capture workflow complete for RUN=$runName" -ForegroundColor Green

