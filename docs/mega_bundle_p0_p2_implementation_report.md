# Отчёт: Mega Bundle P0–P2 + audit polish

**Дата:** 2026-07-18  
**План (studio):** `hometutor-studio/doc/next/mega_bundle_catalog_plan.md`  
**Статус:** P0-1…P2 + audit fixes + residual data_dir + optional polish (owner order UI)

---

## Волны (кратко)

| Волна | Статус |
|--------|--------|
| P0-1 compiler floors | ✅ |
| P0-2a thin library | ✅ |
| P1 address / badge / catalog.list | ✅ |
| P0-2b schedule UI | ✅ |
| P2 course lanes | ✅ |
| Audit glue (5 items) | ✅ |
| Residual Settings.data_dir + path_safety | ✅ |
| Optional polish: owner order UI | ✅ |

---

## Audit fixes (кратко)

1. `catalog.list` — section-only query (скан секций до отсечения конспекта).
2. `navigate_to_ask("")` очищает stale `qa_sidebar_folder_rel`.
3. `ScheduleTile.source_paths` → activate scope.
4. `get_data_dir()` / `Settings.data_dir`; path helpers через settings.
5. Усилены тесты; `path_safety.DATA_DIR` re-export для legacy monkeypatch.
6. Validator re-root `user_state_db` / `auth_db` / LLM cache under `data_dir`.

---

## Optional polish (этот шаг)

- **`app/course_owner_order.py`** — session key `library_course_owner_order`, move ↑/↓.
- **Библиотека:** expander «Порядок курсов (линии в зале)» — без precedes.
- **Каталог-плитки** и **KG payload** / 3D lanes уважают owner order.
- **`tests/path_fixtures.patch_data_dir`** — постепенная миграция тестов (media_audio).
- **`tests/test_course_owner_order.py`**.

---

## Kill switches (сохранены)

- Нет cross-course `precedes` «для красоты».
- Owner order = presentation / recommend only.
- Нет второго graph storage / LLM для порядка.

---

## Manual smoke

1. Библиотека → Порядок курсов → ↑/↓ → плитки «#1 / #2».
2. Knowledge Graph → 3D local/all: primary lane color следует owner order.
3. Rebuild графа / export hall на эталоне (по желанию).

---

## Коммиты

Агент не коммитил без запроса владельца. Сверять `git status` перед фиксацией.
