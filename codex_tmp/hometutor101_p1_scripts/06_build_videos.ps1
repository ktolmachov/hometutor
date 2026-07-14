param(
    [string]$RepoRoot = "D:\Projects\hometutor-studio",
    [string]$CourseDir = "doc\courses\hometutor_101",
    [string]$BuildDir = "",
    [string]$VoiceoverDir = "",
    [switch]$Overwrite
)

. "$PSScriptRoot\common.ps1"

$repo = Resolve-RepoRoot $RepoRoot
$course = Get-CourseDir -RepoRoot $repo -CourseDir $CourseDir
if (-not $BuildDir.Trim()) {
    $BuildDir = Join-Path $course "video_scripts\_build"
}
$manifestDir = Join-Path $BuildDir "manifests"
$segmentRoot = Join-Path $BuildDir "segments"
$outDir = Join-Path $course "videos"
New-Item -ItemType Directory -Force -Path $segmentRoot, $outDir | Out-Null

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpeg) {
    throw "ffmpeg not found in PATH. Install ffmpeg or add it to PATH before running this script."
}

function Escape-DrawText {
    param([string]$Text)
    return ($Text -replace "\\", "\\\\" -replace ":", "\:" -replace "'", "\\'" -replace "`r?`n", " ")
}

function Invoke-Ffmpeg {
    param([string[]]$Arguments)
    Invoke-Checked -FilePath $ffmpeg.Source -Arguments $Arguments -WorkingDirectory $repo
}

$manifests = Get-ChildItem -LiteralPath $manifestDir -Filter "video_*.json" -File | Sort-Object Name
if ($manifests.Count -eq 0) {
    throw "No manifests found in $manifestDir. Run 05_build_video_manifests.ps1 first."
}

foreach ($manifestFile in $manifests) {
    $manifest = Get-Content -Raw -LiteralPath $manifestFile.FullName | ConvertFrom-Json
    $videoName = [string]$manifest.videoName
    $videoSegments = Join-Path $segmentRoot $videoName
    New-Item -ItemType Directory -Force -Path $videoSegments | Out-Null

    $concatPath = Join-Path $videoSegments "concat.txt"
    if (Test-Path -LiteralPath $concatPath) {
        Remove-Item -LiteralPath $concatPath -Force
    }

    foreach ($item in $manifest.items) {
        $idx = "{0:00}" -f [int]$item.index
        $duration = [double]$item.durationSec
        $segmentPath = Join-Path $videoSegments "$idx.mp4"
        if ((Test-Path -LiteralPath $segmentPath) -and -not $Overwrite) {
            Write-Host "Segment exists, skip: $segmentPath"
        } elseif ($item.kind -eq "image") {
            $frames = [int][math]::Ceiling($duration * [int]$manifest.fps)
            $vf = "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,zoompan=z='min(zoom+0.0008,1.06)':d=${frames}:s=1920x1080:fps=$($manifest.fps),format=yuv420p"
            Invoke-Ffmpeg -Arguments @(
                "-y",
                "-loop", "1",
                "-i", [string]$item.fullPath,
                "-vf", $vf,
                "-t", ([string]$duration),
                "-an",
                "-r", ([string]$manifest.fps),
                $segmentPath
            )
        } else {
            $title = Escape-DrawText ([string]$item.frameCell)
            $subtitle = Escape-DrawText ([string]$item.visible)
            $font = "C\:/Windows/Fonts/arial.ttf"
            $vf = "drawtext=fontfile='$font':text='$title':fontcolor=white:fontsize=70:x=(w-text_w)/2:y=h*0.42,drawtext=fontfile='$font':text='$subtitle':fontcolor=#cfd7ff:fontsize=34:x=(w-text_w)/2:y=h*0.56,format=yuv420p"
            Invoke-Ffmpeg -Arguments @(
                "-y",
                "-f", "lavfi",
                "-i", "color=c=#101522:s=1920x1080:d=$duration",
                "-vf", $vf,
                "-an",
                "-r", ([string]$manifest.fps),
                $segmentPath
            )
        }
        Add-Content -LiteralPath $concatPath -Value ("file '{0}'" -f ($segmentPath -replace "'", "'\''"))
    }

    $silentOut = Join-Path $outDir "$videoName.silent.mp4"
    Invoke-Ffmpeg -Arguments @(
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", $concatPath,
        "-c", "copy",
        $silentOut
    )

    $finalOut = Join-Path $outDir "$videoName.mp4"
    $voice = $null
    if ($VoiceoverDir.Trim()) {
        $wav = Join-Path $VoiceoverDir "$videoName.wav"
        $mp3 = Join-Path $VoiceoverDir "$videoName.mp3"
        if (Test-Path -LiteralPath $wav -PathType Leaf) { $voice = $wav }
        elseif (Test-Path -LiteralPath $mp3 -PathType Leaf) { $voice = $mp3 }
    }

    if ($voice) {
        Invoke-Ffmpeg -Arguments @(
            "-y",
            "-i", $silentOut,
            "-i", $voice,
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            $finalOut
        )
    } else {
        Copy-Item -LiteralPath $silentOut -Destination $finalOut -Force
    }
    Write-Host "Video: $finalOut" -ForegroundColor Green
}

Write-Host ""
Write-Host "Video build complete: $outDir" -ForegroundColor Green
