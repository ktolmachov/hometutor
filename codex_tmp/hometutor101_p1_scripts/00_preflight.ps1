param(
    [string]$RepoRoot = "D:\Projects\hometutor-studio",
    [string]$RuntimeRepoRoot = "D:\Projects\hometutor",
    [string]$CourseDir = "doc\courses\hometutor_101",
    [string]$Run = "",
    [switch]$SkipKonspektValidation,
    [switch]$SkipDemoFinalGate
)

. "$PSScriptRoot\common.ps1"

$repo = Resolve-RepoRoot $RepoRoot
$runtime = Resolve-RuntimeRoot $RuntimeRepoRoot
$course = Get-CourseDir -RepoRoot $repo -CourseDir $CourseDir
$python = Get-StudioPython $repo

Write-Host "studio:  $repo"
Write-Host "runtime: $runtime"
Write-Host "course:  $course"
Write-Host "studio HEAD:  $(Get-GitShortHead $repo)"
Write-Host "runtime HEAD: $(Get-GitShortHead $runtime)"

$required = @(
    "package.json",
    "scripts\demo_workflow.py",
    "scripts\validate_demo_contract.py",
    "scripts\make_demo_gifs.py",
    "scripts\generate_demo_doc.py",
    "scripts\validate_smart_konspekt.py",
    "doc\screenshots\final",
    "doc\scenarios",
    "tests\e2e\demos"
)

foreach ($rel in $required) {
    $path = Join-Path $repo $rel
    Write-Check $rel (Test-Path -LiteralPath $path) $path
}

$videoScripts = Get-ChildItem -LiteralPath (Join-Path $course "video_scripts") -Filter "video_*.md" -File
Write-Check "video scripts count" ($videoScripts.Count -eq 6) "$($videoScripts.Count)/6"

$konspekts = Get-ChildItem -LiteralPath (Join-Path $course "konspekts") -Filter "*.konspekt.md" -File
Write-Check "konspekts count" ($konspekts.Count -eq 6) "$($konspekts.Count)/6"

if (-not $SkipKonspektValidation) {
    foreach ($k in $konspekts) {
        Invoke-Checked -FilePath $python -Arguments @(
            "scripts\validate_smart_konspekt.py",
            $k.FullName,
            "--profile",
            "local"
        ) -WorkingDirectory $repo
    }
}

Invoke-Checked -FilePath $python -Arguments @("scripts\check_scenario_ids.py") -WorkingDirectory $repo

if ($Run.Trim()) {
    $runName = Get-RunName $Run
    Invoke-Checked -FilePath $python -Arguments @(
        "scripts\demo_workflow.py",
        "--run",
        $runName,
        "list"
    ) -WorkingDirectory $repo
    Invoke-Checked -FilePath $python -Arguments @(
        "scripts\demo_workflow.py",
        "--run",
        $runName,
        "preflight"
    ) -WorkingDirectory $repo
} else {
    Write-Host ""
    Write-Host "No -Run provided; skipping dated RUN inventory and validating published final/ instead." -ForegroundColor Yellow
}

if (-not $SkipDemoFinalGate) {
    Invoke-Checked -FilePath $python -Arguments @(
        "scripts\validate_demo_contract.py",
        "--screenshots-dir",
        "doc\screenshots\final",
        "--require-screenshots",
        "--strict-captures",
        "--require-unique-shots"
    ) -WorkingDirectory $repo
}

Write-Host ""
Write-Host "Preflight complete." -ForegroundColor Green
