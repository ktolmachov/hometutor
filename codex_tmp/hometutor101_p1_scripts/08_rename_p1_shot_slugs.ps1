param(
    [string]$RepoRoot = "D:\Projects\hometutor-studio",
    [switch]$Apply
)

. "$PSScriptRoot\common.ps1"

$repo = Resolve-RepoRoot $RepoRoot

$replacements = @(
    [pscustomobject]@{
        Scenario = "scenario_36"
        Old = "01_route_day_auto_step"
        New = "01_route_day_auto"
    },
    [pscustomobject]@{
        Scenario = "scenario_37"
        Old = "01_konspekt_quality_status_step"
        New = "01_konspekt_quality_passport"
    },
    [pscustomobject]@{
        Scenario = "scenario_37"
        Old = "02_konspekt_quality_status_step"
        New = "02_konspekt_status_controls"
    },
    [pscustomobject]@{
        Scenario = "scenario_37"
        Old = "03_konspekt_quality_status_step"
        New = "03_konspekt_status_counters"
    },
    [pscustomobject]@{
        Scenario = "scenario_38"
        Old = "01_appearance_worlds_step"
        New = "01_appearance_worlds"
    }
)

function Get-ScenarioFiles {
    param(
        [string]$RepoRoot,
        [string]$Scenario
    )

    $yamlFiles = @(Get-ChildItem -LiteralPath (Join-Path $RepoRoot "doc\scenarios") -Filter "$Scenario*.yaml" -File)
    $specFiles = @(Get-ChildItem -LiteralPath (Join-Path $RepoRoot "tests\e2e\demos") -Filter "$Scenario*.spec.ts" -File)
    return @($yamlFiles + $specFiles)
}

function Update-SlugFile {
    param(
        [string]$Path,
        [array]$ScenarioReplacements
    )

    $oldText = Get-Content -Raw -LiteralPath $Path
    $newText = $oldText
    $changes = New-Object System.Collections.Generic.List[string]

    foreach ($replacement in $ScenarioReplacements) {
        if ($newText.Contains($replacement.Old)) {
            $newText = $newText.Replace($replacement.Old, $replacement.New)
            $changes.Add("$($replacement.Old) -> $($replacement.New)")
        } elseif ($newText.Contains($replacement.New)) {
            Write-Host "Already renamed in ${Path}: $($replacement.New)" -ForegroundColor DarkGray
        } else {
            Write-Warning "Neither old nor new slug found in ${Path}: $($replacement.Old) / $($replacement.New)"
        }
    }

    if ($changes.Count -eq 0) {
        return
    }

    if ($Apply) {
        Set-Content -LiteralPath $Path -Value $newText -Encoding UTF8
        Write-Host "Updated: $Path" -ForegroundColor Green
    } else {
        Write-Host "Would update: $Path" -ForegroundColor Yellow
    }

    foreach ($change in $changes) {
        Write-Host "  $change"
    }
}

$allScenarioIds = $replacements | Select-Object -ExpandProperty Scenario -Unique

foreach ($scenario in $allScenarioIds) {
    $files = Get-ScenarioFiles -RepoRoot $repo -Scenario $scenario
    if ($files.Count -eq 0) {
        Write-Warning "No YAML/spec files found for $scenario. Run scaffold first."
        continue
    }

    $scenarioReplacements = @($replacements | Where-Object { $_.Scenario -eq $scenario })
    foreach ($file in $files) {
        Update-SlugFile -Path $file.FullName -ScenarioReplacements $scenarioReplacements
    }
}

if (-not $Apply) {
    Write-Host ""
    Write-Host "Preview only. Re-run with -Apply to write changes." -ForegroundColor Yellow
}
