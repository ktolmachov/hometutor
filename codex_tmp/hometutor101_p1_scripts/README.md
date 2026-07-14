# hometutor 101 P1 scripts

Набор скриптов для закрытия P1 курса `hometutor 101`: доснять реальные кадры,
обновить video scripts и собрать видео по раскадровкам.

Запускать из PowerShell. По умолчанию все скрипты работают с:

- studio repo: `D:\Projects\hometutor-studio`
- runtime repo: `D:\Projects\hometutor`
- course dir: `doc\courses\hometutor_101`

Рекомендуемый порядок:

```powershell
.\00_preflight.ps1
.\01_inventory_missing_frames.ps1
.\02_capture_demo_run.ps1 -ScenarioId scenario_21,scenario_25,scenario_26,scenario_31,scenario_33,scenario_34,scenario_35
.\03_publish_and_sync.ps1 -Run 2026-07-14 -SyncRuntime
.\04_patch_video_scripts.ps1 -Apply `
  -RouteFrame "scenario_36/01_route_day_auto.png" `
  -PassportFrame "scenario_37/01_konspekt_quality_passport.png" `
  -StatusControlsFrame "scenario_37/02_konspekt_status_controls.png" `
  -StatusCountersFrame "scenario_37/03_konspekt_status_counters.png" `
  -AppearanceFrame "scenario_38/01_appearance_worlds.png"
.\05_build_video_manifests.ps1
.\06_build_videos.ps1
.\07_final_gate.ps1
```

Если новые кадры будут добавлены не как `scenario_36..38`, передай реальные
пути в `04_patch_video_scripts.ps1`. Путь кадра всегда относительный к
`doc\screenshots\final`, например `scenario_40/02_status_counters.png`.

`04_patch_video_scripts.ps1` без `-Apply` работает как preview и не пишет файлы.
`03_publish_and_sync.ps1 -SyncRuntime` копирует опубликованные кадры из
`hometutor-studio\doc\screenshots\final` в
`hometutor\docs\screenshots\final`.

Видео собираются без аудио, если не передать `-VoiceoverDir`. Если рядом есть
`video_1_pervyi_otvet.wav` или `.mp3`, скрипт замиксует его в итоговый mp4.

