param(
    [string]$RepoRoot = "D:\Projects\hometutor-studio",
    [string]$RuntimeRepoRoot = "D:\Projects\hometutor",
    [string]$CourseDir = "doc\courses\hometutor_101",
    [switch]$SkipDemoGate,
    [switch]$SkipKonspektGate,
    [switch]$RequireVideos
)

. "$PSScriptRoot\common.ps1"

$repo = Resolve-RepoRoot $RepoRoot
$runtime = Resolve-RuntimeRoot $RuntimeRepoRoot
$course = Get-CourseDir -RepoRoot $repo -CourseDir $CourseDir
$python = Get-StudioPython $repo

$errors = New-Object System.Collections.Generic.List[string]

function Add-GateError {
    param([string]$Message)
    $errors.Add($Message)
    Write-Host "FAIL  $Message" -ForegroundColor Red
}

$videoScripts = Get-ChildItem -LiteralPath (Join-Path $course "video_scripts") -Filter "video_*.md" -File | Sort-Object Name
foreach ($script in $videoScripts) {
    $text = Get-Content -Raw -LiteralPath $script.FullName
    $lineNo = 0
    foreach ($line in ($text -split "`r?`n")) {
        $lineNo += 1
        $isStoryboardPlaceholder = $line -match '^\|\s*\d+\s*\|.*\|\s*[^|`]*\*\s*\|'
        $isOpenP1Note = $line -match 'ещё не снят|еще не снят|пока не снят|до съёмки|До съёмки|^\s*-\s*P1:|\(`\*`\)'
        if ($isStoryboardPlaceholder -or $isOpenP1Note) {
            Add-GateError "Open capture marker remains in $($script.Name):$lineNo"
        }
    }
    foreach ($m in [regex]::Matches($text, '`([^`]+scenario_\d{2}/[^`]+\.png)`')) {
        $rel = $m.Groups[1].Value
        $path = Get-FinalScreenshotPath -RepoRoot $repo -RelativeFrame $rel
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            Add-GateError "Missing frame referenced by $($script.Name): $rel"
        }
    }
}

if (-not $SkipKonspektGate) {
    $konspekts = Get-ChildItem -LiteralPath (Join-Path $course "konspekts") -Filter "*.konspekt.md" -File
    foreach ($k in $konspekts) {
        try {
            Invoke-Checked -FilePath $python -Arguments @(
                "scripts\validate_smart_konspekt.py",
                $k.FullName,
                "--profile",
                "local"
            ) -WorkingDirectory $repo
        } catch {
            Add-GateError "Konspekt validation failed: $($k.Name)"
        }
    }
}

if (-not $SkipDemoGate) {
    try {
        Invoke-Checked -FilePath $python -Arguments @(
            "scripts\validate_demo_contract.py",
            "--screenshots-dir",
            "doc\screenshots\final",
            "--require-screenshots",
            "--strict-captures",
            "--require-unique-shots"
        ) -WorkingDirectory $repo
    } catch {
        Add-GateError "Demo final contract failed."
    }
}

if ($RequireVideos) {
    $videoDir = Join-Path $course "videos"
    foreach ($script in $videoScripts) {
        $stem = [System.IO.Path]::GetFileNameWithoutExtension($script.Name)
        $mp4 = Join-Path $videoDir "$stem.mp4"
        if (-not (Test-Path -LiteralPath $mp4 -PathType Leaf)) {
            Add-GateError "Missing rendered video: $mp4"
            continue
        }
        $len = (Get-Item -LiteralPath $mp4).Length
        if ($len -lt 100000) {
            Add-GateError "Rendered video looks too small: $mp4 ($len bytes)"
        }
    }
}

$runtimeFinal = Join-Path $runtime "docs\screenshots\final"
foreach ($sid in @("scenario_31", "scenario_33", "scenario_34", "scenario_35")) {
    $studioPath = Join-Path (Join-Path $repo "doc\screenshots\final") $sid
    $runtimePath = Join-Path $runtimeFinal $sid
    Write-Check "studio final $sid" (Test-Path -LiteralPath $studioPath -PathType Container) $studioPath
    Write-Check "runtime final $sid" (Test-Path -LiteralPath $runtimePath -PathType Container) $runtimePath
}

Write-Host ""
if ($errors.Count -gt 0) {
    Write-Host "Final gate failed: $($errors.Count) issue(s)." -ForegroundColor Red
    exit 1
}

Write-Host "Final gate passed." -ForegroundColor Green
