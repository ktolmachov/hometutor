# «Ответ под присягой» — Semantic Groundedness: Plan

**Разбор №25 · hometutor · HEAD 07c8a2a · Коммит #336 · 2026-07-19**

---

## Статус

| Параметр | Значение |
|---|---|
| E1 (код/конфиг) | ✅ верифицировано |
| E2 (живой семпл) | 🔴 missing — live endpoint недоступен в сессии |
| SGAR baseline | не измерен |
| P0 выбран | да (на основе E1) |

---

## North Star

**SGAR** = Semantic Grounded Answer Rate

```
SGAR = count(ответов, где каждый существенный claim entailed из источника
             AND OOC обработан корректно)
     / count(оценённых ответов)
```

Целевой процент не назначается до первого живого E2 baseline.

---

## Пользовательский контракт

> «Каждое существенное утверждение ответа либо доказуемо следует из конкретного фрагмента учебного материала, который можно открыть и проверить, либо явно маркируется как недостаточно подкреплённое; если данных в корпусе нет — система говорит это прямо.»

---

## Ключевые E1-факты

### Центральный разрыв: `build_provenance_ledger` не включает chunk_text

```python
# app/grounded_answer.py:233-244
def build_provenance_ledger(schema, *, retrieval_confidence=None):
    for fact in schema.facts:
        for prov in fact.provenance:
            ledger.append({
                "fact_text": fact.text,
                "cite_index": prov.cite_index,
                "relative_path": prov.relative_path,   # путь к файлу
                "provenance_type": prov.provenance_type,
                # ← НЕТ chunk_text: пара (утверждение, текст-источника) недоступна
            })
```

Source-объект содержит `text` (подтверждено: gate-скрипт `_sources_text()` строка 349).  
Но при построении ledger источники не передаются → chunk_text потерян.

### Cache-hit bypass

```python
# app/grounded_answer.py:461
if not settings.grounded_answer_contract_enabled or cache_hit:
    return GroundedValidationResult(answer_text=answer_text, skipped=True)
```

Все cache-hit ответы возвращаются без grounding-проверки. Флаг не различает «grounded» от «skipped» в debug.

Дополнительные bypass (тот же файл):
- `answer_path_mode == "two_stage_early"` → строка 471
- `not sources` → строка 464  
- Guardrail violation (empty/pii/suspicious) → строки 476-482

### home_rag_gate не в CI

`.github/workflows/ci.yml` запускает: ruff, pytest, arch_regression_guards.  
`scripts/home_rag_integration_gate_v1.py` — не упоминается.

Gate запускается с `GROUNDED_ANSWER_STRICT_QA=0` (строка 184 скрипта) — намеренно relaxed.  
15 eval-кейсов проверяют: keyword presence, cite bounds, OOC no-citation.  
Semantic entailment, numeric fidelity — не проверяются.

### Что НЕ делает `_build_facts_from_text`

```python
# app/grounded_answer.py:183-215
# Для каждого блока текста:
#   1. Парсит [N] маркеры
#   2. Проверяет cite_index в source_lookup (структурно)
#   3. Строит CitationProvenance{cite_index, relative_path}
# НЕ делает: загрузку текста чанка, сравнение claim с chunk
```

### Метрика citation_coverage существует, но не видна студенту

```python
# app/grounded_answer.py:247-251
def _citation_coverage(facts):
    cited = sum(1 for fact in facts if fact.provenance)
    return round(cited / len(facts), 4)
# → кладётся в debug.citation_coverage, не в UI
```

---

## P0 — Два хода (выбраны на E1, до E2)

### P0-A: chunk_text в провенанс-ледже

**Боль:** пара (утверждение, текст источника) недоступна в API-ответе → невозможна offline semantic eval.

**Write-set:** `app/grounded_answer.py::build_provenance_ledger` + callers в `app/query_service.py`

**Изменение:**

```python
# Текущая сигнатура
def build_provenance_ledger(
    schema: GroundedAnswerSchema | AbstainResponse | None,
    *,
    retrieval_confidence: Any = None,
) -> list[dict[str, Any]] | dict[str, Any]:

# Предлагаемое изменение:
def build_provenance_ledger(
    schema: GroundedAnswerSchema | AbstainResponse | None,
    *,
    retrieval_confidence: Any = None,
    sources: list[dict[str, Any]] | None = None,  # ← ДОБАВИТЬ
) -> list[dict[str, Any]] | dict[str, Any]:

# В теле функции добавить в ledger.append():
    source_lookup = _source_by_cite_index(sources or [])
    # ...
    source = source_lookup.get(prov.cite_index, {})
    chunk_text = str(source.get("text") or "")  # уже есть в source-объекте
    ledger.append({
        "fact_text": fact.text,
        "cite_index": prov.cite_index,
        "relative_path": prov.relative_path,
        "provenance_type": prov.provenance_type,
        "chunk_text": chunk_text,  # ← НОВОЕ
    })
```

**Acceptance criteria:**
- `response.debug.provenance_ledger[*].chunk_text` — непустое когда source.text доступен
- Существующие тесты не ломаются (параметр optional)

**Тест:** добавить в `tests/test_guardrails_invariants.py` или `tests/test_query_response_postprocessing.py`:
- `build_provenance_ledger(schema, sources=[...])` → каждый entry содержит `chunk_text`
- `build_provenance_ledger(schema)` → `chunk_text` отсутствует или `""` (backward compat)

**Observability:** `response.debug.provenance_ledger[*].chunk_text`

**Effort:** ~2ч

**Kill switch:** если payload вырастает критически → включать только при `debug_mode=True` в QueryOptions

---

### P0-B: Cache-hit grounding parity flag

**Боль:** cache-hit возвращает `skipped=True` без объяснения причины → eval не отличает «grounded» от «пропущено из-за кэша».

**Write-set:** `app/grounded_answer.py::apply_grounded_validation` (1 строка)

**Изменение:**

```python
# app/grounded_answer.py:461 — текущее:
if not settings.grounded_answer_contract_enabled or cache_hit:
    return GroundedValidationResult(answer_text=answer_text, skipped=True)

# Предлагаемое:
if not settings.grounded_answer_contract_enabled or cache_hit:
    skip_reason = "cache_hit" if cache_hit else "contract_disabled"
    return GroundedValidationResult(
        answer_text=answer_text,
        skipped=True,
        debug={"grounding_skipped": skip_reason},  # ← ДОБАВИТЬ
    )
```

**Acceptance criteria:**
- `response.debug.grounding_skipped == "cache_hit"` при cache-hit ответе
- `response.debug.grounding_skipped == "contract_disabled"` при отключённом контракте

**Тест:**
```python
result = apply_grounded_validation(
    answer_text="some text", sources=[...],
    cache_hit=True, query_mode="qa",
    homework_mode=False, assistance_level=None,
)
assert result.debug.get("grounding_skipped") == "cache_hit"
```

**Observability:** API debug поле, логируется в response

**Effort:** ~30 мин

**Kill switch:** revert 1 строки

---

## P1 — Следующий уровень (после E1+E2)

### P1-A: Token-overlap evidence binding script

**Файл:** `scripts/evidence_binding_check.py` [NEW]

Читает провенанс-ледже из API debug (после P0-A), вычисляет per-claim overlap score:

```python
def token_overlap(claim: str, chunk: str) -> float:
    tokens_claim = set(claim.lower().split())
    tokens_chunk = set(chunk.lower().split())
    if not tokens_claim:
        return 0.0
    return len(tokens_claim & tokens_chunk) / len(tokens_claim)
```

Output: JSON с claim-level scores + aggregate SGAR proxy.

**Dependency:** P0-A

**Effort:** ~4ч

---

### P1-B: Operator protocol — home_rag_gate

Добавить в `docs/conventions_reference.md` или создать `docs/operator_runbook.md`:

```
# Обязательный preflight перед реиндексом или сменой модели/промпта:
.\.venv\Scripts\python.exe scripts/home_rag_integration_gate_v1.py --preflight-only
```

15 кейсов gate покрывают structural regression. Для полного прогона (с LLM):
```
.\.venv\Scripts\python.exe scripts/home_rag_integration_gate_v1.py \
    --llm-base-url http://127.0.0.1:8080/v1 \
    --llm-model <model_id>
```

**Effort:** ~1ч

---

## P2 — Offline LLM-judge (после E2)

**Файл:** `eval_data/sgar_baseline_v1.json` [NEW]

Запустить E2 семпл (15 ответов × 5 категорий по рубрике §4 разбора).  
LLM-judge оценивает R3 (entailment) и R5 (synthesis).  
Первый числовой SGAR baseline.  
Judge той же модели — только proxy, явно помечен.

**Dependency:** P0-A + P1-A + живой endpoint

**Effort:** ~1 рабочий день

---

## E2: Методология (зафиксирована, выполнение pending)

**Условия прогона (фиксируются до генерации):**
- Модель / профиль: balanced (local_strict fallback)
- Промпт qa: qa@2.2 (`app/prompts/_impl.py`)
- Промпт synthesis: synthesis@2.1
- Retrieval: hybrid BM25+vector, top_k=5
- Корпус: активный `data/` пользователя
- Cache: LLM_REQUEST_CACHE_PERSIST=true
- HEAD: 07c8a2a · #336
- GROUNDED_ANSWER_STRICT_QA: true (live, не gate)

**Категории (5 × 3 = 15):**
1. Прямой факт из одного источника
2. Синтез из нескольких источников
3. Конфликтующие / неоднозначные источники
4. Вопрос вне корпуса (OOC)
5. Числовой / citation / cache-hit trap

**Рубрика (R1–R8, предзафиксирована):**
- R1: Выделены существенные claims
- R2: Citation target существует (deterministic)
- R3: Entailment: claim ← chunk text (offline LLM proxy)
- R4: Числа, единицы, отрицания сохранены (regex + human)
- R5: Multi-source synthesis корректен (offline LLM proxy)
- R6: Citation completeness — все claims покрыты (deterministic)
- R7: Abstention correctness для OOC (deterministic)
- R8: Answer usefulness (human only)

---

## Kill Switch

Остановить или вынести из P0, если ход:
- Требует нового DB/schema/хранилища → **нет** (P0-A: поле в existing debug, P0-B: поле в existing debug)
- Добавляет runtime LLM-judge → **нет** (LLM только в P2 offline)
- Считает наличие cite_index доказательством истинности → **нет**
- Отключает существующий grounded guard → **нет**
- Требует полной переработки retrieval → **нет**
- Назначает baseline без живого измерения → **нет** (SGAR target не назначается)
- Скрывает cache-hit/cache-miss → **нет** (P0-B делает обратное)

---

## Связи с предыдущими разборами

| Разбор | Тема | Отличие от №25 |
|---|---|---|
| №5 | Устойчивость доставки ответа | Не проверял истинность утверждений |
| №10 | Видимость trace | Observability, не groundedness |
| №11 | Сценарии использования | Покрытие use-cases, не semantic binding |
| №24 | Качество квизов и честность mastery | Mastery, не provenance пары (утверждение, источник) |

---

*Документ создан: 2026-07-19 · HEAD 07c8a2a · E1 verified · E2 missing*
