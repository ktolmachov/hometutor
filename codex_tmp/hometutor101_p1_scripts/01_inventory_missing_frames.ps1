param(
    [string]$RepoRoot = "D:\Projects\hometutor-studio",
    [string]$CourseDir = "doc\courses\hometutor_101",
    [string]$OutFile = "",
    [switch]$FailOnFindings
)

. "$PSScriptRoot\common.ps1"

$repo = Resolve-RepoRoot $RepoRoot
$course = Get-CourseDir -RepoRoot $repo -CourseDir $CourseDir
$finalRoot = Join-Path $repo "doc\screenshots\final"
$videoDir = Join-Path $course "video_scripts"

$expectedLogicalFrames = @(
    [pscustomobject]@{ Key="route_day_auto"; UsedBy="video_4"; Description="Кнопка/результат Авто: маршрут дня"; Suggested="scenario_36/01_route_day_auto.png" },
    [pscustomobject]@{ Key="konspekt_quality_passport"; UsedBy="video_5"; Description="Паспорт качества конспекта, рубрика 10 критериев"; Suggested="scenario_37/01_konspekt_quality_passport.png" },
    [pscustomobject]@{ Key="konspekt_status_controls"; UsedBy="video_5"; Description="Статусы раздела: понял / сомневаюсь / не понял"; Suggested="scenario_37/02_konspekt_status_controls.png" },
    [pscustomobject]@{ Key="konspekt_status_counters"; UsedBy="video_5"; Description="Счётчики понято / сомневаюсь / вопросов открыто"; Suggested="scenario_37/03_konspekt_status_counters.png" },
    [pscustomobject]@{ Key="appearance_worlds"; UsedBy="video_6"; Description="Вкладка Оформление с мирами Лес/Океан/Закат/Космос/Ягода"; Suggested="scenario_38/01_appearance_worlds.png" }
)

$rows = @()
foreach ($frame in $expectedLogicalFrames) {
    $suggestedPath = Get-FinalScreenshotPath -RepoRoot $repo -RelativeFrame $frame.Suggested
    $rows += [pscustomobject]@{
        Type = "expected-p1"
        Key = $frame.Key
        UsedBy = $frame.UsedBy
        Description = $frame.Description
        RelativeFrame = $frame.Suggested
        Exists = Test-Path -LiteralPath $suggestedPath -PathType Leaf
        FullPath = $suggestedPath
    }
}

$scripts = Get-ChildItem -LiteralPath $videoDir -Filter "video_*.md" -File
foreach ($script in $scripts) {
    $text = Get-Content -Raw -LiteralPath $script.FullName
    $lineNo = 0
    foreach ($line in ($text -split "`r?`n")) {
        $lineNo += 1
        $isStoryboardPlaceholder = $line -match '^\|\s*\d+\s*\|.*\|\s*[^|`]*\*\s*\|'
        $isOpenP1Note = $line -match 'ещё не снят|еще не снят|пока не снят|до съёмки|До съёмки|^\s*-\s*P1:|\(`\*`\)'
        if ($isStoryboardPlaceholder -or $isOpenP1Note) {
            $rows += [pscustomobject]@{
                Type = "open-marker"
                Key = ""
                UsedBy = $script.Name
                Description = "Open marker at line $lineNo"
                RelativeFrame = ""
                Exists = $false
                FullPath = $line.Trim()
            }
        }
        foreach ($m in [regex]::Matches($line, '`([^`]+scenario_\d{2}/[^`]+\.png)`')) {
            $rel = $m.Groups[1].Value
            $path = Get-FinalScreenshotPath -RepoRoot $repo -RelativeFrame $rel
            $rows += [pscustomobject]@{
                Type = "referenced-frame"
                Key = ""
                UsedBy = $script.Name
                Description = "Referenced at line $lineNo"
                RelativeFrame = $rel
                Exists = Test-Path -LiteralPath $path -PathType Leaf
                FullPath = $path
            }
        }
    }
}

$rows | Sort-Object Type, UsedBy, RelativeFrame | Format-Table -AutoSize

$missing = $rows | Where-Object { $_.Type -ne "open-marker" -and -not $_.Exists }
$markers = $rows | Where-Object { $_.Type -eq "open-marker" }

Write-Host ""
Write-Host "Missing referenced/expected frames: $($missing.Count)"
Write-Host "Open textual markers: $($markers.Count)"

if ($OutFile.Trim()) {
    $out = [System.IO.Path]::GetFullPath($OutFile)
    $rows | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $out -Encoding UTF8
    Write-Host "Inventory written: $out"
}

if ($FailOnFindings -and ($missing.Count -gt 0 -or $markers.Count -gt 0)) {
    exit 2
}
