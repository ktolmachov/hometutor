param(
    [string]$RepoRoot = "D:\Projects\hometutor-studio",
    [string]$CourseDir = "doc\courses\hometutor_101",
    [string]$OutDir = ""
)

. "$PSScriptRoot\common.ps1"

$repo = Resolve-RepoRoot $RepoRoot
$course = Get-CourseDir -RepoRoot $repo -CourseDir $CourseDir
if (-not $OutDir.Trim()) {
    $OutDir = Join-Path $course "video_scripts\_build"
}
$manifestDir = Join-Path $OutDir "manifests"
$srtDir = Join-Path $OutDir "subtitles"
New-Item -ItemType Directory -Force -Path $manifestDir, $srtDir | Out-Null

function Convert-TimeToSeconds {
    param([string]$Value)
    $parts = $Value.Split(":")
    if ($parts.Count -eq 2) {
        return ([int]$parts[0] * 60 + [int]$parts[1])
    }
    if ($parts.Count -eq 3) {
        return ([int]$parts[0] * 3600 + [int]$parts[1] * 60 + [int]$parts[2])
    }
    throw "Unsupported timecode: $Value"
}

function Format-SrtTime {
    param([double]$Seconds)
    $ts = [TimeSpan]::FromSeconds($Seconds)
    return "{0:00}:{1:00}:{2:00},{3:000}" -f [int]$ts.TotalHours, $ts.Minutes, $ts.Seconds, $ts.Milliseconds
}

$scripts = Get-ChildItem -LiteralPath (Join-Path $course "video_scripts") -Filter "video_*.md" -File | Sort-Object Name
foreach ($script in $scripts) {
    $text = Get-Content -Raw -LiteralPath $script.FullName
    $items = @()
    $srtLines = New-Object System.Collections.Generic.List[string]
    $captionIndex = 0

    foreach ($line in ($text -split "`r?`n")) {
        if ($line -notmatch '^\|\s*(\d+)\s*\|\s*([0-9:]+)–([0-9:]+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*«(.+)»\s*\|') {
            continue
        }
        $idx = [int]$Matches[1]
        $start = Convert-TimeToSeconds $Matches[2]
        $end = Convert-TimeToSeconds $Matches[3]
        $frameCell = $Matches[4].Trim()
        $visible = $Matches[5].Trim()
        $narration = $Matches[6].Trim()
        $duration = [math]::Max(1.0, $end - $start)

        $kind = "title"
        $relativeFrame = ""
        $fullPath = ""
        if ($frameCell -match '`([^`]+\.png)`') {
            $kind = "image"
            $relativeFrame = $Matches[1]
            $fullPath = Get-FinalScreenshotPath -RepoRoot $repo -RelativeFrame $relativeFrame
            if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
                throw "Missing frame for $($script.Name) row ${idx}: $relativeFrame ($fullPath)"
            }
        }

        $items += [pscustomobject]@{
            index = $idx
            startSec = $start
            endSec = $end
            durationSec = $duration
            kind = $kind
            frameCell = $frameCell
            visible = $visible
            narration = $narration
            relativeFrame = $relativeFrame
            fullPath = $fullPath
        }

        $captionIndex += 1
        $srtLines.Add([string]$captionIndex)
        $srtLines.Add("$(Format-SrtTime $start) --> $(Format-SrtTime $end)")
        $srtLines.Add($narration)
        $srtLines.Add("")
    }

    if ($items.Count -eq 0) {
        throw "No storyboard rows parsed from $($script.FullName)"
    }

    $manifest = [pscustomobject]@{
        source = $script.FullName
        videoName = [System.IO.Path]::GetFileNameWithoutExtension($script.Name)
        width = 1920
        height = 1080
        fps = 30
        items = $items
    }
    $manifestPath = Join-Path $manifestDir ($manifest.videoName + ".json")
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

    $srtPath = Join-Path $srtDir ($manifest.videoName + ".srt")
    $srtLines | Set-Content -LiteralPath $srtPath -Encoding UTF8
    Write-Host "Manifest: $manifestPath"
    Write-Host "Subtitles: $srtPath"
}

Write-Host ""
Write-Host "Video manifests complete: $manifestDir" -ForegroundColor Green

