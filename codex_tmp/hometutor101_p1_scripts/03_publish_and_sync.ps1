param(
    [string]$RepoRoot = "D:\Projects\hometutor-studio",
    [string]$RuntimeRepoRoot = "D:\Projects\hometutor",
    [string]$Run = "",
    [string[]]$ScenarioId = @(),
    [switch]$FastGifs,
    [switch]$SyncRuntime
)

. "$PSScriptRoot\common.ps1"

$repo = Resolve-RepoRoot $RepoRoot
$runtime = Resolve-RuntimeRoot $RuntimeRepoRoot
$python = Get-StudioPython $repo
$runName = Get-RunName $Run
$shots = "doc\screenshots\$runName"
$envMap = @{ DEMO_SHOT_RUN = $runName; PYTHONIOENCODING = "utf-8" }

Write-Host "RUN: $runName"
Write-Host "Publishing from: $shots"

$workflowBase = @("scripts\demo_workflow.py", "--run", $runName)
foreach ($sid in $ScenarioId) {
    if ($sid -notmatch '^scenario_\d{2}$') {
        throw "ScenarioId must look like scenario_21, got: $sid"
    }
    $workflowBase += @("--scenario-id", $sid)
}

$gifArgs = $workflowBase + @("gifs")
if ($FastGifs) { $gifArgs += "--fast" }
Invoke-Checked -FilePath $python -Arguments $gifArgs -WorkingDirectory $repo -Environment $envMap
Invoke-Checked -FilePath $python -Arguments ($workflowBase + @("preview")) -WorkingDirectory $repo -Environment $envMap
Invoke-Checked -FilePath $python -Arguments ($workflowBase + @("publish")) -WorkingDirectory $repo -Environment $envMap
Invoke-Checked -FilePath $python -Arguments ($workflowBase + @("validate", "--use-final")) -WorkingDirectory $repo -Environment $envMap

if ($SyncRuntime) {
    $sourceFinal = Assert-ChildPath -Parent $repo -Child (Join-Path $repo "doc\screenshots\final")
    $destFinal = Assert-ChildPath -Parent $runtime -Child (Join-Path $runtime "docs\screenshots\final")
    if (-not (Test-Path -LiteralPath $destFinal -PathType Container)) {
        New-Item -ItemType Directory -Path $destFinal | Out-Null
    }

    $syncIds = if ($ScenarioId.Count -gt 0) { $ScenarioId } else { @("scenario_31", "scenario_32", "scenario_33", "scenario_34", "scenario_35") }
    foreach ($sid in $syncIds) {
        $src = Join-Path $sourceFinal $sid
        if (-not (Test-Path -LiteralPath $src -PathType Container)) {
            Write-Warning "Skip runtime sync, missing source: $src"
            continue
        }
        $dst = Join-Path $destFinal $sid
        Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
        Write-Host "Synced $sid -> $dst"
    }
}

Write-Host ""
Write-Host "Publish/sync complete." -ForegroundColor Green

