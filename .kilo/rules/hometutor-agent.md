# hometutor — правила для Kilo Code (VS Code extension / CLI)

Этот файл — **Kilo-специфичный overlay**. Жёсткие runtime-правила, тесты и doc-sync —
в `AGENTS.md` (читать section-only: «Жёсткие правила», «Тесты», «Документация»).
Код-границы — `docs/conventions*.md`. Claude Code — `CLAUDE.md`.

## Kilo Code vs Cursor (VS Code ext)

| Что | Kilo Code | Cursor |
|---|---|---|
| Универсальные инструкции | `AGENTS.md` (auto) | через `.cursor/rules/` → `AGENTS.md` |
| Tool-specific rules | `.kilo/rules/*.md` + `kilo.jsonc` → `instructions` | `.cursor/rules/*.mdc` |
| Процесс / token budget | этот файл + `AGENTS.md` | `base-agent.mdc`, `workflow.mdc`, `llm-request-policy.mdc` |
| Claude overlay | `CLAUDE.md` (compat) | `CLAUDE.md` в `workflow.mdc` |

**Приоритет:** явный промпт пользователя → tool-specific rules → `AGENTS.md` → `docs/conventions*.md` → код.

**Синхронизация:** меняя agent-инструкции, обновляйте оба слоя только если правило относится к обоим инструментам:
- общее (write-set, pytest, git, config/provider) → `AGENTS.md`;
- Kilo-only → `.kilo/rules/`;
- Cursor-only → `.cursor/rules/`.

Не дублируйте в `.kilo/rules/` полный текст `AGENTS.md` — только дельты и матрицу выше.

## Рабочий процесс (Kilo)

1. Сначала минимальный контекст: grep/read по символам, не целиком большие файлы.
2. Перед правками зафиксируй write-set; не выходи за него.
3. Python-команды: `.\.venv\Scripts\python.exe` (fallback `python`/`py`).
4. Тесты: только targeted `pytest` по затронутой зоне; полный suite — только по явному запросу.
5. `git commit` / `git push` — только по явной просьбе пользователя.
6. Backlog / user stories — репозиторий `hometutor-studio`, не этот checkout.
7. `doc/archive/` — legacy; актуальная docs-root — `docs/`.

## Write-protected в Kilo

`AGENTS.md` и `AGENT.md` защищены от правок агентом в Kilo. Чтобы изменить универсальные правила —
попросите пользователя явно или правьте файл вне auto-write guard.
