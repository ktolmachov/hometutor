param(
    [string]$RepoRoot = "D:\Projects\hometutor-studio",
    [string]$RuntimeRepoRoot = "D:\Projects\hometutor",
    [string]$Run = "",
    [string]$VoiceoverDir = "",
    [switch]$AllowTodo,
    [switch]$AddUserScenarioHeadings,
    [switch]$SkipCapture,
    [switch]$SkipVideos,
    [switch]$FastGifs
)

. "$PSScriptRoot\common.ps1"

$repo = Resolve-RepoRoot $RepoRoot
$runtime = Resolve-RuntimeRoot $RuntimeRepoRoot
$python = Get-StudioPython $repo
$runName = Get-RunName $Run
$scenarioIds = @("scenario_36", "scenario_37", "scenario_38")

$expectedSlugs = @{
    "scenario_36" = @("01_route_day_auto")
    "scenario_37" = @(
        "01_konspekt_quality_passport",
        "02_konspekt_status_controls",
        "03_konspekt_status_counters"
    )
    "scenario_38" = @("01_appearance_worlds")
}

$headings = @{
    "scenario_36" = "## Сценарий 36 — Маршрут дня: авто-выбор узлов по ценности"
    "scenario_37" = "## Сценарий 37 — Конспект: паспорт, статусы и счётчики"
    "scenario_38" = "## Сценарий 38 — Оформление: миры темы"
}

$scenarioNumbers = @{
    "scenario_36" = "36"
    "scenario_37" = "37"
    "scenario_38" = "38"
}

$scenarioBodies = @{
    "scenario_36" = @"
Марк открывает Knowledge Graph перед учебным днём. Вместо ручного выбора узлов он нажимает «Авто: маршрут дня» и получает короткий маршрут из тем с максимальной учебной ценностью: где подошёл срок повторения, где знание просело, где узел открывает больше следующих шагов.

**Результат:** карта знаний превращается в практический план на сегодня, а не остаётся обзорной визуализацией.
"@
    "scenario_37" = @"
Аня читает Живой конспект и раскрывает паспорт качества: видит рубрику, проверку точности и сильные/слабые места материала. После чтения раздела она отмечает статус «Понял», «Сомневаюсь» или «Не понял», оставляет открытый вопрос и видит общий счётчик прогресса по конспекту.

**Результат:** чтение становится измеримым учебным действием: понятно, какие разделы закрыты, а какие надо вернуть в тьютор или повторение.
"@
    "scenario_38" = @"
Аня вечером открывает «Настроить интерфейс» и переходит во вкладку «Оформление». Она выбирает один из визуальных миров — Лес, Океан, Закат, Космос или Ягода — чтобы интерфейс был комфортнее для длинного чтения и повторения.

**Результат:** персонализация остаётся локальной настройкой профиля и не меняет учебные данные.
"@
}

function Get-ScenarioPair {
    param(
        [string]$RepoRoot,
        [string]$ScenarioId
    )
    $yaml = @(Get-ChildItem -LiteralPath (Join-Path $RepoRoot "doc\scenarios") -Filter "$ScenarioId*.yaml" -File)
    $spec = @(Get-ChildItem -LiteralPath (Join-Path $RepoRoot "tests\e2e\demos") -Filter "$ScenarioId*.spec.ts" -File)
    if ($yaml.Count -ne 1) {
        throw "Expected exactly one YAML for $ScenarioId, found $($yaml.Count)."
    }
    if ($spec.Count -ne 1) {
        throw "Expected exactly one spec for $ScenarioId, found $($spec.Count)."
    }
    return [pscustomobject]@{ Yaml = $yaml[0]; Spec = $spec[0] }
}

function Assert-ScenarioReady {
    param(
        [string]$ScenarioId,
        [System.IO.FileInfo]$Yaml,
        [System.IO.FileInfo]$Spec
    )

    $yamlText = Get-Content -Raw -LiteralPath $Yaml.FullName
    $specText = Get-Content -Raw -LiteralPath $Spec.FullName
    $combined = $yamlText + "`n" + $specText

    foreach ($slug in $expectedSlugs[$ScenarioId]) {
        if ($yamlText -notmatch "slug:\s*`"$([regex]::Escape($slug))`"") {
            throw "$ScenarioId YAML does not contain expected slug: $slug"
        }
        if ($specText -notmatch "demo\.shot\(`"$([regex]::Escape($slug))`"") {
            throw "$ScenarioId spec does not contain expected demo.shot slug: $slug"
        }
    }

    if (-not $AllowTodo -and $combined -match "TODO:|// TODO") {
        throw "$ScenarioId still contains TODO markers. Implement YAML text and Playwright navigation first, or rerun with -AllowTodo for a dry/experimental pass."
    }
}

function Ensure-UserScenarioHeadings {
    param([string]$RepoRoot)

    $path = Join-Path $RepoRoot "doc\user_scenarios.md"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing doc\user_scenarios.md at $path"
    }

    $text = Get-Content -Raw -LiteralPath $path
    $added = New-Object System.Collections.Generic.List[string]
    foreach ($scenarioId in $scenarioIds) {
        $num = $scenarioNumbers[$scenarioId]
        $line = $headings[$scenarioId]
        $body = $scenarioBodies[$scenarioId].Trim()

        $legacyPattern = "(?ms)^##\s+$scenarioId\s+—.*?(?=^##\s+|\z)"
        if ($text -match $legacyPattern) {
            $replacement = $line + "`r`n`r`n" + $body + "`r`n`r`n"
            $text = [regex]::Replace($text, $legacyPattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $replacement }, 1)
            $added.Add("Replaced legacy heading: $line")
            continue
        }

        if ($text -notmatch "(?m)^##\s+Сценарий\s+$num\s+—") {
            $text = $text.TrimEnd() + "`r`n`r`n" + $line + "`r`n`r`n" + $body + "`r`n"
            $added.Add($line)
        }
    }

    if ($added.Count -gt 0) {
        Set-Content -LiteralPath $path -Value $text -Encoding UTF8
        Write-Host "Added headings to doc\user_scenarios.md:" -ForegroundColor Green
        foreach ($line in $added) {
            Write-Host "  $line"
        }
    } else {
        Write-Host "doc\user_scenarios.md already has valid scenario 36–38 headings." -ForegroundColor Green
    }
}

Write-Host "studio:  $repo"
Write-Host "runtime: $runtime"
Write-Host "RUN:     $runName"

$pairs = @{}
foreach ($scenarioId in $scenarioIds) {
    $pair = Get-ScenarioPair -RepoRoot $repo -ScenarioId $scenarioId
    $pairs[$scenarioId] = $pair
    Write-Host "$scenarioId YAML: $($pair.Yaml.FullName)"
    Write-Host "$scenarioId SPEC: $($pair.Spec.FullName)"
    Assert-ScenarioReady -ScenarioId $scenarioId -Yaml $pair.Yaml -Spec $pair.Spec
}

if ($AddUserScenarioHeadings) {
    Ensure-UserScenarioHeadings -RepoRoot $repo
} else {
    Write-Host "Skipping doc\user_scenarios.md heading write. Use -AddUserScenarioHeadings if check_scenario_ids.py needs it." -ForegroundColor Yellow
}

foreach ($scenarioId in $scenarioIds) {
    Invoke-Checked -FilePath $python -Arguments @(
        "scripts\demo_workflow.py",
        "--run",
        $runName,
        "--scenario-id",
        $scenarioId,
        "preflight"
    ) -WorkingDirectory $repo -Environment @{ DEMO_SHOT_RUN = $runName; PYTHONIOENCODING = "utf-8" }
}

if (-not $SkipCapture) {
    & "$PSScriptRoot\02_capture_demo_run.ps1" `
        -RepoRoot $repo `
        -Run $runName `
        -ScenarioId $scenarioIds `
        -FastGifs:$FastGifs
    if ($LASTEXITCODE -ne 0) {
        throw "02_capture_demo_run.ps1 failed with exit code $LASTEXITCODE"
    }
} else {
    Write-Host "Skipping capture by request." -ForegroundColor Yellow
}

& "$PSScriptRoot\03_publish_and_sync.ps1" `
    -RepoRoot $repo `
    -RuntimeRepoRoot $runtime `
    -Run $runName `
    -ScenarioId $scenarioIds `
    -FastGifs:$FastGifs `
    -SyncRuntime
if ($LASTEXITCODE -ne 0) {
    throw "03_publish_and_sync.ps1 failed with exit code $LASTEXITCODE"
}

& "$PSScriptRoot\04_patch_video_scripts.ps1" -RepoRoot $repo -Apply
if ($LASTEXITCODE -ne 0) {
    throw "04_patch_video_scripts.ps1 failed with exit code $LASTEXITCODE"
}

if (-not $SkipVideos) {
    & "$PSScriptRoot\05_build_video_manifests.ps1" -RepoRoot $repo
    if ($LASTEXITCODE -ne 0) {
        throw "05_build_video_manifests.ps1 failed with exit code $LASTEXITCODE"
    }

    $videoArgs = @{
        RepoRoot = $repo
    }
    if ($VoiceoverDir.Trim()) {
        $videoArgs["VoiceoverDir"] = $VoiceoverDir
    }
    & "$PSScriptRoot\06_build_videos.ps1" @videoArgs
    if ($LASTEXITCODE -ne 0) {
        throw "06_build_videos.ps1 failed with exit code $LASTEXITCODE"
    }
} else {
    Write-Host "Skipping video manifest/mp4 build by request." -ForegroundColor Yellow
}

& "$PSScriptRoot\07_final_gate.ps1" -RepoRoot $repo -RuntimeRepoRoot $runtime -RequireVideos:(!$SkipVideos)
if ($LASTEXITCODE -ne 0) {
    throw "07_final_gate.ps1 failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "hometutor 101 P1 pipeline complete." -ForegroundColor Green
