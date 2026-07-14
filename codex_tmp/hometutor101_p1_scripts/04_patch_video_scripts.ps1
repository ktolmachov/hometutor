param(
    [string]$RepoRoot = "D:\Projects\hometutor-studio",
    [string]$CourseDir = "doc\courses\hometutor_101",
    [string]$RouteFrame = "scenario_36/01_route_day_auto.png",
    [string]$PassportFrame = "scenario_37/01_konspekt_quality_passport.png",
    [string]$StatusControlsFrame = "scenario_37/02_konspekt_status_controls.png",
    [string]$StatusCountersFrame = "scenario_37/03_konspekt_status_counters.png",
    [string]$AppearanceFrame = "scenario_38/01_appearance_worlds.png",
    [switch]$Apply,
    [switch]$AllowMissingFrames
)

. "$PSScriptRoot\common.ps1"

$repo = Resolve-RepoRoot $RepoRoot
$course = Get-CourseDir -RepoRoot $repo -CourseDir $CourseDir

$frames = @($RouteFrame, $PassportFrame, $StatusControlsFrame, $StatusCountersFrame, $AppearanceFrame)
foreach ($frame in $frames) {
    $path = Get-FinalScreenshotPath -RepoRoot $repo -RelativeFrame $frame
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $msg = "Frame not found: $frame ($path)"
        if ($AllowMissingFrames) { Write-Warning $msg } else { throw $msg }
    }
}

function Update-FileText {
    param(
        [string]$Path,
        [scriptblock]$Transform
    )
    $old = Get-Content -Raw -LiteralPath $Path
    $new = & $Transform $old
    if ($old -eq $new) {
        Write-Warning "No changes produced for $Path"
        return
    }
    if ($Apply) {
        Set-Content -LiteralPath $Path -Value $new -Encoding UTF8
        Write-Host "Updated: $Path" -ForegroundColor Green
    } else {
        Write-Host "Would update: $Path" -ForegroundColor Yellow
        Compare-Object ($old -split "`r?`n") ($new -split "`r?`n") | Select-Object -First 40
    }
}

$video4 = Join-Path $course "video_scripts\video_4_karta_znaniy.md"
$video5 = Join-Path $course "video_scripts\video_5_konspekt_s_pasportom.md"
$video6 = Join-Path $course "video_scripts\video_6_khozyain_sistemy.md"

Update-FileText -Path $video4 -Transform {
    param($text)
    $text = $text -replace '\| 5 \| 0:38–0:50 \| `scenario_25/02_graduated_concepts\.png` \| экран освоения, graduated \| «Закреплённые концепты система помнит и убирает из плана пробелов\. А новые остановки выбирает кнопка „Авто: маршрут дня“ — по цене узла, с причиной у каждой\.» \|',
        ('| 5 | 0:38–0:50 | `{0}` | кнопка «Авто: маршрут дня» и список остановок с причинами | «Новые остановки выбирает кнопка „Авто: маршрут дня“ — по цене узла, с причиной у каждой.» |' -f $RouteFrame)
    $text = $text -replace '- Кнопка «Авто: маршрут дня» упоминается голосом на кадре 5 без отдельного кадра\r?\n  \(кадр в витрине пока не снят\); не подменять мокапом — только реальные кадры\.',
        "- P1-кадр «Авто: маршрут дня» снят реальным Playwright-конвейером; мокапы не используются."
    return $text
}

Update-FileText -Path $video5 -Transform {
    param($text)
    $text = $text -replace '\| 2 \| 0:07–0:19 \| Кадр читалки конспекта с паспортом качества\* \| рубрика 10 критериев; зум на «Проверка точности» \|',
        ('| 2 | 0:07–0:19 | `{0}` | рубрика 10 критериев; зум на «Проверка точности» |' -f $PassportFrame)
    $text = $text -replace '\| 3 \| 0:19–0:31 \| Кадр раздела со статусами\* \| кнопки «понял / сомневаюсь / не понял» \|',
        ('| 3 | 0:19–0:31 | `{0}` | кнопки «понял / сомневаюсь / не понял» |' -f $StatusControlsFrame)
    $text = $text -replace '\| 6 \| 0:55–1:07 \| Кадр счётчиков на главном экране\* \| «понято / сомневаюсь / вопросов открыто» \|',
        ('| 6 | 0:55–1:07 | `{0}` | «понято / сомневаюсь / вопросов открыто» |' -f $StatusCountersFrame)
    $text = $text -replace '- Кадры, помеченные `\*`, в витрине ещё не сняты \(фичи паспорта и статусов\r?\n  отгружены недавно\): снять по конвейеру Playwright новые манифесты или,\r?\n  до съёмки, использовать живой скринкаст этих экранов\. \*\*Мокапы запрещены\*\* —\r?\n  правило витрины: только реальные кадры продукта\.',
        "- P1-кадры паспорта, статусов и счётчиков сняты реальным Playwright-конвейером. Мокапы запрещены и не используются."
    return $text
}

Update-FileText -Path $video6 -Transform {
    param($text)
    $text = $text -replace '\| 7 \| 1:03–1:13 \| Кадр вкладки «Оформление» с мирами\* \| пять миров тем \|',
        ('| 7 | 1:03–1:13 | `{0}` | пять миров тем |' -f $AppearanceFrame)
    $text = $text -replace '- Кадр 7 \(`\*`\) в витрине ещё не снят \(вкладка «Оформление» отгружена недавно\) —\r?\n  снять манифестом по конвейеру или живым скринкастом\. Мокапы запрещены\.',
        "- P1-кадр вкладки «Оформление» снят реальным Playwright-конвейером. Мокапы запрещены и не используются."
    return $text
}

if (-not $Apply) {
    Write-Host ""
    Write-Host "Preview only. Re-run with -Apply to write changes." -ForegroundColor Yellow
}
