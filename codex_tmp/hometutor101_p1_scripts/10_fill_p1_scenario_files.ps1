param(
    [string]$RepoRoot = "D:\Projects\hometutor-studio",
    [switch]$Apply
)

. "$PSScriptRoot\common.ps1"

$repo = Resolve-RepoRoot $RepoRoot

$scenario36Yaml = @'
id: scenario_36
title: "Маршрут дня: авто-выбор узлов по ценности"
level: "🔴 Mastery"
persona: "Марк готовится к экзамену и хочет не просто красивый граф, а короткий список узлов, с которых сегодня выгоднее начать."
duration_min: 2
why: |
  Показать, что Knowledge Graph умеет выбирать следующий учебный маршрут по worth:
  due, novelty, decay, frontier и reach складываются в конкретные остановки на день.
requires:
  openai_api_key: false
  offline_friendly: true
wow_moment: |
  Кнопка «Авто: маршрут дня» превращает карту знаний в маршрут из нескольких остановок по ценности.
takeaway: |
  Граф не декоративный: он помогает решить, что учить сейчас, а что можно оставить на потом.
scenario_link: "user_scenarios.md#сценарий-36--маршрут-дня-авто-выбор-узлов-по-ценности"

shots:
  - slug: "01_route_day_auto"
    caption: "Knowledge Graph: авто-маршрут дня"
    narration: "Один клик выбирает 4–6 узлов с максимальной учебной ценностью и подсвечивает путь на графе."
    duration_sec: 6
'@

$scenario36Spec = @'
import { test, type Frame, type Page } from "@playwright/test";
import { createDemoRecorder } from "../fixtures/demo_recorder";
import { DEMO } from "../fixtures/demo_timeouts";
import { completeFirstRunOnboarding } from "../fixtures/onboarding";
import { gotoAndWaitForStreamlitReady, waitForStreamlitReady } from "../fixtures/streamlit_ready";

async function findFrameWithSelector(page: Page, selector: string, label: string): Promise<Frame> {
  const deadline = Date.now() + DEMO.visibleMs;
  let scannedFrames = 0;
  while (Date.now() < deadline) {
    const frames = page.frames();
    scannedFrames = frames.length;
    for (const frame of frames) {
      const match = frame.locator(selector).first();
      if (await match.count().catch(() => 0)) {
        return frame;
      }
    }
    await page.waitForTimeout(250);
  }
  throw new Error(`${label} not found in any Playwright frame; scanned ${scannedFrames} frame(s).`);
}

test.describe("@demo Scenario 36 — маршрут дня", () => {
  test("@demo captures KG auto day route", async ({ page }) => {
    test.setTimeout(180_000);
    const demo = createDemoRecorder(page, "scenario_36");

    try {
      await completeFirstRunOnboarding(page);
      await gotoAndWaitForStreamlitReady(page, "/?e2e_view=kg");
      await page.getByText(/Knowledge Graph|подграф|граф/i).first().waitFor({
        state: "visible",
        timeout: DEMO.visibleMs,
      }).catch(() => null);
      await waitForStreamlitReady(page);

      const graph = await findFrameWithSelector(page, "#routebtn", "KG route toolbar");
      await graph.locator("#routebtn").click({ timeout: DEMO.visibleMs });
      await graph.locator("#rp-day").click({ timeout: DEMO.visibleMs });
      await graph.locator("#rp-steps").getByText(/Маршрут дня|остановок по ценности/i).first().waitFor({
        state: "visible",
        timeout: DEMO.visibleMs,
      });
      await waitForStreamlitReady(page);

      await demo.shot("01_route_day_auto", {
        caption: "Knowledge Graph: авто-маршрут дня",
        narration: "Один клик выбирает 4–6 узлов с максимальной учебной ценностью и подсвечивает путь на графе.",
        fullPage: true,
        waitMs: 800,
      });

      await demo.finalize("passed");
    } catch (err) {
      await demo.finalize("failed");
      throw err;
    }
  });
});
'@

$scenario37Yaml = @'
id: scenario_37
title: "Конспект: паспорт, статусы и счётчики"
level: "🟠 Retention engine"
persona: "Аня читает живой конспект и хочет понимать не только текст, но и качество источника, свой статус по разделам и остаток открытых вопросов."
duration_min: 3
why: |
  Зафиксировать свежие фичи Живого конспекта: паспорт качества, статусы «Понял / Сомневаюсь / Не понял»
  и счётчики, которые превращают чтение в управляемую учебную работу.
requires:
  openai_api_key: false
  offline_friendly: true
wow_moment: |
  Конспект показывает качество и прогресс прямо рядом с разделом: не надо помнить в голове, что уже закрыто.
takeaway: |
  Хороший конспект в hometutor — это не статичный markdown, а рабочая поверхность с качеством, статусами и вопросами.
scenario_link: "user_scenarios.md#сценарий-37--конспект-паспорт-статусы-и-счётчики"

shots:
  - slug: "01_konspekt_quality_passport"
    caption: "Паспорт качества конспекта"
    narration: "Рубрика качества раскрывается рядом с разделом и показывает, где есть проверка точности."
    duration_sec: 5
  - slug: "02_konspekt_status_controls"
    caption: "Статусы раздела: понял, сомневаюсь, не понял"
    narration: "После чтения можно зафиксировать состояние знания и оставить вопрос тьютору."
    duration_sec: 5
  - slug: "03_konspekt_status_counters"
    caption: "Счётчики прогресса по конспекту"
    narration: "Система собирает статусы в общий обзор: что закрыто, что сомнительно, где остались вопросы."
    duration_sec: 5
'@

$scenario37Spec = @'
import { test, type Page } from "@playwright/test";
import { createDemoRecorder } from "../fixtures/demo_recorder";
import { DEMO } from "../fixtures/demo_timeouts";
import { completeFirstRunOnboarding } from "../fixtures/onboarding";
import { gotoAndWaitForStreamlitReady, waitForStreamlitReady } from "../fixtures/streamlit_ready";

function main(page: Page) {
  return page.locator('[data-testid="stMain"]').first();
}

async function requireVisibleText(page: Page, pattern: RegExp, label: string) {
  const target = main(page).getByText(pattern).first();
  await target.waitFor({ state: "visible", timeout: DEMO.visibleMs }).catch(() => {
    throw new Error(`${label} was not visible. Check that offline demo data contains a living konspekt with this feature.`);
  });
  await target.scrollIntoViewIfNeeded().catch(() => undefined);
  await waitForStreamlitReady(page);
}

async function addFirstSectionToWorkbench(page: Page) {
  const addButton = page.getByRole("button", { name: /^➕$/ }).first();
  await addButton.waitFor({ state: "visible", timeout: DEMO.visibleMs });
  await addButton.click({ timeout: DEMO.visibleMs });
  await page.getByRole("tab", { name: /Читать/i }).waitFor({ state: "visible", timeout: DEMO.visibleMs });
  await waitForStreamlitReady(page);
}

async function openFirstAvailableExpander(page: Page, pattern: RegExp) {
  const expander = page.getByText(pattern).last();
  await expander.waitFor({ state: "visible", timeout: DEMO.visibleMs });
  await expander.scrollIntoViewIfNeeded().catch(() => undefined);
  await expander.click({ timeout: 5_000 }).catch(() => undefined);
  await page.waitForTimeout(500);
}

test.describe("@demo Scenario 37 — конспект: качество и статусы", () => {
  test("@demo captures quality passport, section statuses and counters", async ({ page }) => {
    test.setTimeout(180_000);
    const demo = createDemoRecorder(page, "scenario_37");

    try {
      await completeFirstRunOnboarding(page);
      await gotoAndWaitForStreamlitReady(page, "/?e2e_view=living_konspekt");
      await waitForStreamlitReady(page);
      await addFirstSectionToWorkbench(page);
      await page.getByRole("tab", { name: /Читать/i }).click({ timeout: DEMO.visibleMs });
      await waitForStreamlitReady(page);

      await requireVisibleText(page, /богатый\s*\+\s*рубрика|рубрика/i, "quality passport marker");
      await demo.shot("01_konspekt_quality_passport", {
        caption: "Паспорт качества конспекта",
        narration: "В паспорте раздела видно, что конспект богатый и прошёл рубрику качества.",
        fullPage: true,
        waitMs: 700,
      });

      await openFirstAvailableExpander(page, /Содержимое раздела/i);
      await requireVisibleText(page, /Понял|Сомневаюсь|Не понял/i, "section status controls");
      await demo.shot("02_konspekt_status_controls", {
        caption: "Статусы раздела: понял, сомневаюсь, не понял",
        narration: "После чтения можно зафиксировать состояние знания и оставить вопрос тьютору.",
        fullPage: true,
        waitMs: 700,
      });

      await page.getByRole("button", { name: /Понял/i }).first().click({ timeout: DEMO.visibleMs });
      await page.getByText(/Статус:\s*Понял|В корзине:\s*[1-9]/i).first().waitFor({
        state: "visible",
        timeout: DEMO.visibleMs,
      });
      await page.evaluate(() => window.scrollTo(0, 0));
      await requireVisibleText(page, /В корзине:\s*[1-9]|Статус:\s*Понял|нового для тебя/i, "konspekt status counters");
      await demo.shot("03_konspekt_status_counters", {
        caption: "Счётчики прогресса по конспекту",
        narration: "Система собирает статусы в общий обзор: что закрыто, что сомнительно, где остались вопросы.",
        fullPage: true,
        waitMs: 700,
      });

      await demo.finalize("passed");
    } catch (err) {
      await demo.finalize("failed");
      throw err;
    }
  });
});
'@

$scenario38Yaml = @'
id: scenario_38
title: "Оформление: миры темы"
level: "🟢 Everyday UX"
persona: "Аня учится вечером и хочет выбрать спокойную цветовую схему, чтобы интерфейс меньше утомлял."
duration_min: 2
why: |
  Показать, что оформление — это не косметика ради косметики: пользователь может выбрать визуальный мир
  и сохранить его локально в своём профиле.
requires:
  openai_api_key: false
  offline_friendly: true
wow_moment: |
  Панель «Оформление» показывает готовые миры: Лес, Океан, Закат, Космос и Ягода.
takeaway: |
  Hometutor можно настроить под себя без изменения учебных данных и без облака.
scenario_link: "user_scenarios.md#сценарий-38--оформление-миры-темы"

shots:
  - slug: "01_appearance_worlds"
    caption: "Панель оформления: миры темы"
    narration: "Пять цветовых миров помогают быстро подобрать комфортный режим чтения и повторения."
    duration_sec: 6
'@

$scenario38Spec = @'
import { test } from "@playwright/test";
import { createDemoRecorder } from "../fixtures/demo_recorder";
import { DEMO } from "../fixtures/demo_timeouts";
import { completeFirstRunOnboarding } from "../fixtures/onboarding";
import { gotoAndWaitForStreamlitReady, waitForStreamlitReady } from "../fixtures/streamlit_ready";

test.describe("@demo Scenario 38 — оформление: миры темы", () => {
  test("@demo captures appearance worlds panel", async ({ page }) => {
    test.setTimeout(180_000);
    const demo = createDemoRecorder(page, "scenario_38");

    try {
      await completeFirstRunOnboarding(page);
      await gotoAndWaitForStreamlitReady(page, "/?e2e_view=home");
      await waitForStreamlitReady(page);

      await page.getByRole("button", { name: /Настроить интерфейс/i }).first().click({ timeout: DEMO.visibleMs });
      await page.getByRole("tab", { name: /Оформление/i }).click({ timeout: DEMO.visibleMs });
      await page.getByText(/Лес|Океан|Закат|Космос|Ягода/i).first().waitFor({
        state: "visible",
        timeout: DEMO.visibleMs,
      });
      await waitForStreamlitReady(page);

      await demo.shot("01_appearance_worlds", {
        caption: "Панель оформления: миры темы",
        narration: "Пять цветовых миров помогают быстро подобрать комфортный режим чтения и повторения.",
        fullPage: true,
        waitMs: 800,
      });

      await demo.finalize("passed");
    } catch (err) {
      await demo.finalize("failed");
      throw err;
    }
  });
});
'@

$targets = @(
    @{
        Rel = "doc\scenarios\scenario_36_route_day_auto.yaml"
        Content = $scenario36Yaml
    },
    @{
        Rel = "tests\e2e\demos\scenario_36_route_day_auto.spec.ts"
        Content = $scenario36Spec
    },
    @{
        Rel = "doc\scenarios\scenario_37_konspekt_quality_status.yaml"
        Content = $scenario37Yaml
    },
    @{
        Rel = "tests\e2e\demos\scenario_37_konspekt_quality_status.spec.ts"
        Content = $scenario37Spec
    },
    @{
        Rel = "doc\scenarios\scenario_38_appearance_worlds.yaml"
        Content = $scenario38Yaml
    },
    @{
        Rel = "tests\e2e\demos\scenario_38_appearance_worlds.spec.ts"
        Content = $scenario38Spec
    }
)

foreach ($target in $targets) {
    $abs = Assert-ChildPath -Parent $repo -Child (Join-Path $repo $target.Rel)
    if (-not (Test-Path -LiteralPath $abs -PathType Leaf)) {
        throw "Target file not found: $abs"
    }
    if ($target.Content -match "TODO") {
        throw "Generated content still contains TODO marker for $($target.Rel)"
    }
}

if (-not $Apply) {
    Write-Host "Preview mode. The following files will be overwritten. Re-run with -Apply to write:" -ForegroundColor Yellow
    foreach ($target in $targets) {
        $abs = Assert-ChildPath -Parent $repo -Child (Join-Path $repo $target.Rel)
        Write-Host "  $abs"
    }
    exit 0
}

foreach ($target in $targets) {
    $abs = Assert-ChildPath -Parent $repo -Child (Join-Path $repo $target.Rel)
    Set-Content -LiteralPath $abs -Value $target.Content -Encoding UTF8
    Write-Host "Updated: $abs" -ForegroundColor Green
}

$openMarkers = @()
foreach ($target in $targets) {
    $abs = Assert-ChildPath -Parent $repo -Child (Join-Path $repo $target.Rel)
    $matches = Select-String -LiteralPath $abs -Pattern "TODO" -SimpleMatch
    foreach ($match in $matches) {
        $openMarkers += "$($target.Rel):$($match.LineNumber): $($match.Line.Trim())"
    }
}

if ($openMarkers.Count -gt 0) {
    throw "Open markers remain:`n$($openMarkers -join "`n")"
}

Write-Host ""
Write-Host "Done. Next: rerun 09_finish_p1_pipeline.ps1 without -AllowTodo." -ForegroundColor Cyan
