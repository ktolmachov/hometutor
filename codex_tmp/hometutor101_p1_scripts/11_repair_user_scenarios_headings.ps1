param(
    [string]$RepoRoot = "D:\Projects\hometutor-studio",
    [switch]$Apply
)

. "$PSScriptRoot\common.ps1"

$repo = Resolve-RepoRoot $RepoRoot
$python = Get-StudioPython $repo
$path = Join-Path $repo "doc\user_scenarios.md"
if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    throw "Missing doc\user_scenarios.md at $path"
}

$sections = @(
    [pscustomobject]@{
        Id = "scenario_36"
        Num = "36"
        Heading = "## Сценарий 36 — Маршрут дня: авто-выбор узлов по ценности"
        Body = @"
Марк открывает Knowledge Graph перед учебным днём. Вместо ручного выбора узлов он нажимает «Авто: маршрут дня» и получает короткий маршрут из тем с максимальной учебной ценностью: где подошёл срок повторения, где знание просело, где узел открывает больше следующих шагов.

**Результат:** карта знаний превращается в практический план на сегодня, а не остаётся обзорной визуализацией.
"@
    },
    [pscustomobject]@{
        Id = "scenario_37"
        Num = "37"
        Heading = "## Сценарий 37 — Конспект: паспорт, статусы и счётчики"
        Body = @"
Аня читает Живой конспект и раскрывает паспорт качества: видит рубрику, проверку точности и сильные/слабые места материала. После чтения раздела она отмечает статус «Понял», «Сомневаюсь» или «Не понял», оставляет открытый вопрос и видит общий счётчик прогресса по конспекту.

**Результат:** чтение становится измеримым учебным действием: понятно, какие разделы закрыты, а какие надо вернуть в тьютор или повторение.
"@
    },
    [pscustomobject]@{
        Id = "scenario_38"
        Num = "38"
        Heading = "## Сценарий 38 — Оформление: миры темы"
        Body = @"
Аня вечером открывает «Настроить интерфейс» и переходит во вкладку «Оформление». Она выбирает один из визуальных миров — Лес, Океан, Закат, Космос или Ягода — чтобы интерфейс был комфортнее для длинного чтения и повторения.

**Результат:** персонализация остаётся локальной настройкой профиля и не меняет учебные данные.
"@
    }
)

$text = Get-Content -Raw -LiteralPath $path
$changed = $false
$actions = New-Object System.Collections.Generic.List[string]

foreach ($section in $sections) {
    $replacement = $section.Heading + "`r`n`r`n" + $section.Body.Trim() + "`r`n`r`n"
    $legacyPattern = "(?ms)^##\s+$([regex]::Escape($section.Id))\s+—.*?(?=^##\s+|\z)"
    if ($text -match $legacyPattern) {
        $text = [regex]::Replace(
            $text,
            $legacyPattern,
            [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $replacement },
            1
        )
        $changed = $true
        $actions.Add("replace legacy $($section.Id)")
        continue
    }

    $validPattern = "(?m)^##\s+Сценарий\s+$($section.Num)\s+—"
    if ($text -notmatch $validPattern) {
        $text = $text.TrimEnd() + "`r`n`r`n" + $replacement
        $changed = $true
        $actions.Add("append scenario $($section.Num)")
    }
}

if (-not $changed) {
    Write-Host "No changes needed: doc\user_scenarios.md already has valid headings." -ForegroundColor Green
} elseif (-not $Apply) {
    Write-Host "Preview mode. Re-run with -Apply to update doc\user_scenarios.md:" -ForegroundColor Yellow
    foreach ($action in $actions) {
        Write-Host "  $action"
    }
    exit 0
} else {
    Set-Content -LiteralPath $path -Value $text -Encoding UTF8
    Write-Host "Updated doc\user_scenarios.md:" -ForegroundColor Green
    foreach ($action in $actions) {
        Write-Host "  $action"
    }
}

if ($Apply) {
    Invoke-Checked -FilePath $python -Arguments @(
        "scripts\check_scenario_ids.py"
    ) -WorkingDirectory $repo -Environment @{ PYTHONIOENCODING = "utf-8" }
}
