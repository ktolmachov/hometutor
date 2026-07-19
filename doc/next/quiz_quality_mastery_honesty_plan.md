# Quiz Quality & Mastery Honesty — Implementation-Ready Plan
## Разбор №24 · hometutor@07c8a2a8a1b4065e394cb0c70c6bca8f3a239156

**Дата проверки:** 2026-07-19  
**Ветка незакоммиченных изменений:** Route Policy (session_tape, smart_study_*, test_one_route_policy) — не затронута.  
**Prompt revision:** QUIZ_SCOPED_PROMPT встроен в `_impl.py`, нет отдельного version field.

---

## Снимок реальности

```
HEAD: 07c8a2a8a1b4065e394cb0c70c6bca8f3a239156 (commit 336)
Незакоммиченные: M app/session_tape.py, app/smart_study_recommendation.py,
  app/smart_study_router.py, app/ui/adaptive_plan_card.py,
  app/ui/resume_cards_smart_study.py, app/ui/smart_study_next_step_card.py,
  tests/test_one_route_policy.py  ← Route Policy, не трогать
```

---

## Суть (от первых принципов)

> **Квиз честен только если каждый вопрос, влияющий на mastery студента,  
> подтверждён конкретным материалом, имеет ровно один доказуемо правильный  
> ответ и качественные дистракторы. Всё остальное — иллюзия проверки.**

---

## Карта quiz-путей (5 путей)

| Путь | Entry point | Контекст | Промпт | Схема | Structural checks | Content checks | Fallback | Mastery write | Риск |
|------|-------------|----------|--------|-------|-------------------|----------------|----------|---------------|------|
| **PATH-1 Scoped** | `generate_scoped_quiz()` → `generate_scoped_quiz_from_content()` | `explain_file()` / `synthesize_topic_summary()` / living_konspekt | `QUIZ_SCOPED_PROMPT` (T=0.25) | JSON array 5-8: question, options[4], correct_index, difficulty, explanation | `_normalize_scoped_questions()`: count, non-empty, 4 opts, ci 0..3, difficulty ∈ allowed | **НЕТ** | `{success:False}` | `save_quiz_result()` → `apply_quiz_outcome_to_learner_state()` → SM-2 + quiz_mastery | **ВЫСОКИЙ** |
| **PATH-2 Micro** | `generate_and_attach_micro_quiz(ctx)` → `generate_micro_quiz()` | **НЕТ** (тема из last message) | `QUIZ_MICRO_QUIZ_SYSTEM` + `QUIZ_MICRO_QUIZ_USER_TEMPLATE` (chat, T=0.35) | JSON: question, options[4], correct_option(A-D), explanation, difficulty(easy/med/hard), type | `_validate_micro_quiz_payload()`: non-empty, 4 opts, correct A-D, difficulty, type | **НЕТ** | `_fallback_micro_quiz()` ← всегда B=correct, ungrounded | Немедленно: `save_quiz_result()` → `apply_quiz_outcome_to_learner_state()` | **ВЫСОКИЙ** |
| **PATH-3 Tutor Inline** | tutor RAG response + `TUTOR_RAG_V2_INLINE_QUIZ_SUFFIX` или `generate_tutor_inline_quiz_questions()` | RAG context + teaching JSON | `QUIZ_TUTOR_INLINE_QUIZ_FOLLOWUP_PROMPT` (T=0.25) или встроен в tutor prompt | JSON {questions: [1-2]}: type, question, concept, difficulty | `_normalize_inline_questions()`: max 2, non-empty, allowed type/difficulty | **НЕТ** | `[]` | `evaluate_inline_quiz_answer()` → `apply_quiz_outcome_to_learner_state()` | **СРЕДНИЙ** |
| **PATH-4 Interactive** | `generate_interactive_quiz()` | Тема, граф, история | `QUIZ_PROMPT` (4 типа вопросов, T=0.2) | `{quiz_title, questions[n]}`: type/q/options/correct/explanation/concept | `parse_tutor_quiz_llm_json()`: count, все типы, correct per type | **НЕТ** | `(None, error_str)` | `mark_concepts_as_learned()` → knowledge_graph.learned | **СРЕДНИЙ** |
| **PATH-5 Self-Check** | `generate_self_check_quiz()` / `generate_document_quiz()` / `generate_topic_quiz()` | Текст документа / synthesis summary | `QUIZ_SELF_CHECK_PROMPT` | JSON array 5: question, options[4], correct_index | `parse_quiz_json()` + `_normalize_questions()`: ровно 5, 4 opts, ci 0..3. **Нет** difficulty, explanation | **НЕТ** | `([], error_str)` | **НЕТ** (исторически legacy path) | **НИЗКИЙ** по mastery |

### Downstream consumers (подтверждено по символам)

```
apply_quiz_outcome_to_learner_state()
  └─ update_mastery_after_score() → quiz_mastery table (recognition→recall→transfer, SM-2 2-streak)
  └─ record_quiz_score_for_spaced_repetition() → spaced_repetition table

quiz_mastery →
  ├─ get_recommended_difficulty() → adaptive_level в generate_scoped_quiz() [ПЕТЛЯ!]
  ├─ get_weak_concepts() → weak_spot_scoped_quiz_params() → выбор следующей темы
  ├─ mastery_percent_for_level() → estimate_mastery_percent() → motivation line UI
  ├─ get_all_mastery_levels() → learning_plan / konspekt_learning_passport
  └─ list_quiz_mastery_state() → smart_study (через weak_concepts)

Mnemonopolis: render_return_to_mnemo_cta() после scoped quiz completion
Route Policy (SSR/Plan/Worth): косвенно через get_weak_concepts → smart_study
```

---

## Боль-якорь (E1 — confirmed)

**PAIN-02:** требования groundedness и cognitive level записаны в `QUIZ_SCOPED_PROMPT`,
но их соблюдение не проверяется исполняемым content-quality gate до влияния
quiz-outcome на learner state.

**Конкретные факты:**

1. `QUIZ_SCOPED_PROMPT` требует: использовать только предоставленный текст,
   смешивать recognition/recall/transfer, один правильный вариант, explanation.

2. `parse_scoped_quiz_json` / `_normalize_scoped_questions` проверяет:
   count 5-8, non-empty question, ровно 4 options, correct_index 0..3,
   difficulty ∈ {recognition,recall,transfer}, explanation как str (не пустой).

3. **Парсер НЕ доказывает:**
   - что вопрос следует из source scope (нет span matching)
   - что correct_index действительно верен (нет verification)
   - что остальные 3 варианта неверны (нет uniqueness check)
   - что explanation подтверждён материалом (нет grounding)
   - что вопрос с difficulty=transfer реально требует переноса
   - что вопрос не является дублем

4. `apply_quiz_outcome_to_learner_state` обновляет SR и mastery немедленно после
   любого структурно-валидного вопроса (confirmed по коду).

5. Fallback micro quiz: `_fallback_micro_quiz()` всегда возвращает correct_option=B
   на вопрос «что лучше описывает ключевую идею?» — не grounded в материале.
   Тем не менее `process_micro_quiz_outcome()` вызывает `apply_quiz_outcome_to_learner_state()`.

**PAIN-04 (ВТОРИЧНАЯ ГИПОТЕЗА — не подтверждена полностью):**
Пути расходятся по промпту, схеме и fallback-стратегии, но mastery pipeline единый.
Объявлять две независимые линии производства некорректно — это один mastery pipe
с разными входами.

---

## Рубрика (фиксируется до генерации)

| # | Критерий | Тип | Вес |
|---|----------|-----|-----|
| 1 | Stem grounding — вопрос подтверждён конкретным source span | Hard Fail | — |
| 2 | Correct-answer grounding — правильный вариант следует из source | Hard Fail | — |
| 3 | Uniqueness — нет второго допустимого правильного ответа | Hard Fail | — |
| 4 | Distractor validity — дистракторы правдоподобны, опровержимы материалом | Soft | 1/5 |
| 5 | Explanation grounding — объяснение следует из материала | Soft | 1/5 |
| 6 | Cognitive level — независимая классификация совпадает с заявленной | Soft | 1/5 |
| 7 | Clarity — вопрос самодостаточен, не раскрывает ответ | Soft | 1/5 |
| 8 | Duplication — не дублирует другой вопрос в наборе | Soft | 1/5 |

**VLQR** = вопросы с Hard Fail = 0 И Soft Score ≥ 3/5 / все оценённые вопросы

**Примечание:** при одной модели для генерации и оценки — это proxy-оценка.
Ключевые ошибки требуют ручной верификации.

---

## Эталонный семпл (E2 — OFFLINE PROXY)

Выполнить живой семпл невозможно без LLM endpoint в рамках исследовательского
разбора без права менять runtime. Ниже — детерминированный offline анализ на
основе структуры промпта и кода.

### Параметры семпла (зафиксированы здесь до любой генерации)

- Rubric revision: v1.0 (определена выше)
- Model/profile: LOCAL_STRICT (default), QUIZ_SCOPED_PROMPT, temperature=0.25
- Prompt revision: встроен в `_impl.py` @ commit 07c8a2a
- Temperature/seed: 0.25 / не фиксируется (нет seed в `complete_with_resilience`)
- Ожидаемый cognitive target: 1/3 recognition + 1/3 recall + 1/3 transfer per quiz
- Source evidence: полный text из scope (document/topic/living_konspekt)

### Scope плана (5 scope × 3 повтора = 15 генераций)

| Scope # | Тип материала | Cognitive target | Почему сложен |
|---------|--------------|-------------------|---------------|
| S1 | Определения и терминология | recognition (доминант) | риск тривиальных вопросов |
| S2 | Фактический материал (числа, даты, факты) | recall | риск hallucination |
| S3 | Причинно-следственная тема | transfer | риск shallow transfer (label без содержания) |
| S4 | Процедура или применение | recall + transfer | риск ambiguous correct answer |
| S5 | Разреженный/неоднозначный материал | — | риск generation where refusal is better |

### Offline proxy результаты (анализ структуры промпта)

На основе структурного анализа `QUIZ_SCOPED_PROMPT` + `_normalize_scoped_questions`:

**Ожидаемые паттерны ошибок:**

| Критерий | Риск отказа | Обоснование |
|----------|------------|-------------|
| Stem grounding | ~20-30% | Промпт говорит «только из текста», нет enforcement; для S5 риск выше |
| Correct-answer grounding | ~10-15% | Для хорошего контекста LLM обычно берёт верный ответ |
| Uniqueness | ~15-20% | Нет инструкции «докажи что другие варианты неверны» |
| Distractor validity | ~25% | Нет инструкции «для каждого дистрактора укажи почему неверен» |
| Explanation grounding | ~20% | Explanation требуется, но не проверяется связь с source span |
| Cognitive level | ~30-40% | transfer-label ≠ transfer-thinking; нет enforcement |
| Clarity | ~10% | Промпт короткий, но вопросы обычно самодостаточны |
| Duplication | ~5% | 5-8 вопросов, низкий риск |

**Proxy VLQR baseline: ~45-55%**  
*(CI примерный, требует живого семпла для точности)*

**Критический сигнал:** fallback micro quiz (всегда B=correct) записывается в mastery
независимо от реального качества вопроса.

---

## Противоречия и синтезы

| Напряжение | Синтез |
|------------|--------|
| Скорость генерации ↔ доказуемое качество | Детерминированный gate (source_span field) до mastery write; LLM eval только offline/CI |
| Проверка понимания ↔ проверка запоминания | difficulty label + независимая классификация после генерации (не блокирует, но логирует) |
| Разнообразие вопросов ↔ воспроизводимая оценка | Единая рубрика, но разный вес: Hard Fail блокирует mastery write, Soft Score только логируется |
| Качественные дистракторы ↔ однозначный правильный ответ | Промпт + «укажи почему каждый дистрактор неверен» (без LLM-check) |
| Адаптивная сложность ↔ сопоставимость mastery | Mastery обновляется только после validated вопроса; fallback не влияет |
| Детерминированный gate ↔ вероятностный LLM | P0: только source_span (структурный); LLM eval → P1/CI |
| Strict fail-closed ↔ local-first доступность | Confidence tier: VALIDATED/LIMITED/FALLBACK_SKIPPED. Показ с label, mastery write только для VALIDATED |

---

## Вердикты

| Элемент | Решение | Обоснование |
|---------|---------|-------------|
| `QUIZ_SCOPED_PROMPT` | **Усилить** | Добавить поле `source_span` в JSON схему; добавить инструкцию «для каждого дистрактора укажи одно слово/фразу из текста, почему он неверен» |
| `parse_scoped_quiz_json` / `_normalize_scoped_questions` | **Усилить** | Проверять что `source_span` непустой и ≥40 символов; остальные проверки — без изменений |
| `_fallback_micro_quiz` | **Усилить** | Добавить флаг `is_fallback: True`; не передавать в `apply_quiz_outcome_to_learner_state` |
| `process_micro_quiz_outcome` | **Усилить** | Проверять `is_fallback` перед mastery write |
| `QUIZ_MICRO_QUIZ_SYSTEM` + template | **Оставить** | Структурно корректен; нет source context by design (feature, not bug) |
| `QUIZ_SELF_CHECK_PROMPT` | **Оставить** | Нет mastery write — низкий риск |
| `parse_quiz_json` / `_normalize_questions` | **Оставить** | PATH-5 без mastery — низкий риск |
| `QUIZ_PROMPT` (Interactive) | **Оставить** | Пишет в knowledge_graph.learned (не mastery), разная семантика |
| `evaluate_inline_quiz_answer` с LLM | **Оставить** | LLM eval только для free-form; MC — детерминированный |
| `apply_quiz_outcome_to_learner_state` | **Оставить** | Архитектурно правильный; менять не нужно — менять caller |
| Content quality gate (runtime LLM) | **НЕ добавлять** | Kill switch: latency + cost + no proven benefit without live sample |
| VLQR eval script (CI) | **Добавить** | scripts/eval_quiz_quality.py, offline only |

### Нужен ли общий quiz-quality contract?

**Да, минимальный:** для PATH-1 (Scoped) и PATH-2 (Micro) — единое правило:
«вопрос без source_span не обновляет mastery». PATH-3/4/5 — отдельная оценка риска.

### Детерминированные проверки vs evaluator

| Проверка | Тип |
|----------|-----|
| Наличие и длина source_span | Детерминированная (P0) |
| Количество вопросов, count opts, correct_index range | Детерминированная (exists) |
| Дублирование внутри набора | Детерминированная (string similarity, P2) |
| Uniqueness, distractor validity | Требует evaluator (P1/CI) |
| Cognitive level classification | Детерминированная (keyword rules, P2) или evaluator |

### Плохой вопрос: блокировать, регенерировать или показывать?

**Показывать с confidence label, блокировать только mastery write.**
Причина: local-first, latency, нет runtime evaluator.

### Безопасно ли обновлять mastery после вопроса без content gate?

**Нет, если вопрос из fallback или явно ungrounded.** Для остальных — допустим
до появления живого baseline VLQR < 50%.

### Где нужен gate?

- **Online runtime:** только source_span check (детерминированный, нет latency)
- **CI / offline eval:** полная rubric × VLQR скрипт
- **После смены prompt/model:** обязательный re-run eval script
- **Не нужен:** отдельный LLM-judge в runtime до доказанного эффекта

### Что делать с уже сохранённым mastery?

**Не трогать.** Нет audit trail для retroactive invalidation. Задокументировать в README
что mastery до P0 может содержать данные от fallback вопросов.

---

## VLQR — метрика

```
VLQR = |{q : hard_fail(q) = 0 AND soft_score(q) >= 3}| / |evaluated_questions|

hard_fail(q) = 1 если хотя бы одно из:
  - stem_grounding = 0 (нет source_span ≥ 40 символов)
  - correct_grounding = 0 (правильный ответ не следует из span)
  - uniqueness = 0 (есть второй допустимый ответ)

soft_score(q) = sum([distractor_validity, explanation_grounding,
                     cognitive_level, clarity, duplication]) ∈ {0..5}
```

| Параметр | Значение |
|----------|----------|
| Baseline (proxy, N=structural analysis) | ~45-55% |
| Target | ≥75% на живом семпле из 15+ вопросов |
| CI диапазон baseline | ±15% (требует живого семпла) |
| Источник данных | scripts/eval_quiz_quality.py на живом LLM |
| Обоснование target | <75% → mastery write небезопасен без confidence tier |

**Guardrails:**

| Метрика | Тип | Формула/порог |
|---------|-----|---------------|
| parse_success_rate | wired-existing | # successful parse / # attempts |
| fallback_rate | wire-in-P0 | # is_fallback=True / # micro quiz |
| latency | wired-existing | latency_budget.meta |
| cost | not-measurable | нет live endpoint в исследовании |
| validated_transfer_rate | wire-in-P1 | # transfer questions passing gate / # transfer questions |
| critical_unsupported_rate | wire-in-P0 | # questions с source_span=empty / # total |

---

## Золотой путь

```
материал
  → generate_scoped_quiz_from_content(content, scope, ...)
  → QUIZ_SCOPED_PROMPT (source_span в схеме)
  → LLM → JSON
  → parse_scoped_quiz_json()
      [структурная проверка: count, opts, ci, difficulty, source_span]
      → если source_span пустой: confidence=LIMITED, не блокировать показ
      → если source_span ≥ 40: confidence=VALIDATED
  → показ студенту с confidence label (при необходимости)
  → ответ студента
  → объяснение с source_span как evidence
  → если VALIDATED: apply_quiz_outcome_to_learner_state() → mastery + SM-2
  → если LIMITED: save_quiz_result() без mastery write, логирование
  → следующий шаг (из quiz_mastery → weak_concepts → smart_study)
```

**Graceful degradation:**

| Уровень | Условие | Действие |
|---------|---------|----------|
| VALIDATED | source_span ≥ 40, структурно OK | Mastery write, полный SR |
| LIMITED | source_span пустой, структурно OK | Показ без mastery write, лог |
| FALLBACK_SKIPPED | `_fallback_micro_quiz()` сработал | Нет mastery write, is_fallback=True |
| REFUSAL | Контекст < 120 символов | `{success: False}`, честный отказ |

---

## Plan P0–P2

### P0a: Quiz Content Contract — source_span field (Ход 1)

**Problem:** QUIZ_SCOPED_PROMPT не требует source evidence citation;
parse_scoped_quiz_json принимает любой структурно-валидный JSON без content checks.
Fallback micro quiz обновляет mastery через тот же path что и live вопрос.

**Evidence:** E1 — разрыв между промптом и парсером (confirmed, L24); fallback
возвращает `correct_option="B"` на шаблонный вопрос без материала (code: quiz_micro.py:83-98).

**Proposed:**
1. В `QUIZ_SCOPED_PROMPT`: добавить в JSON схему поле `source_span` —
   «1-2 предложения или ключевая фраза из материала, на которой основан вопрос».
2. В `_normalize_scoped_questions()`: проверять что `source_span` присутствует
   и имеет длину ≥ 40 символов; если нет — не отклонять вопрос, но устанавливать
   флаг `grounded: False`.
3. В `_fallback_micro_quiz()`: добавить `"is_fallback": True` в возвращаемый dict.
4. В `process_micro_quiz_outcome()`: если `quiz_data.get("is_fallback")` → пропустить
   `apply_quiz_outcome_to_learner_state()`.

**Files:**
- `app/prompts/_impl.py` — QUIZ_SCOPED_PROMPT schema
- `app/quiz_scoped.py` — `_normalize_scoped_questions()`
- `app/quiz_micro.py` — `_fallback_micro_quiz()`, `process_micro_quiz_outcome()`

**DoD:**
- `_normalize_scoped_questions` обрабатывает вопросы без `source_span` без ошибки
  но устанавливает `grounded: False`
- `_fallback_micro_quiz` возвращает `is_fallback: True`
- `process_micro_quiz_outcome` не вызывает `apply_quiz_outcome_to_learner_state` для fallback
- Добавлены тесты: `tests/test_quiz_content_contract.py` (минимум 5 unit tests)

**Metric contract:**
- `critical_unsupported_rate` = доля вопросов с `grounded: False` (wire-in-P0, логируется)
- `fallback_rate` = доля micro quiz с `is_fallback: True` (wire-in-P0)

**Effort:** S (1 день)

**Dependencies:** нет

**Kill switch:** если `source_span` в промпте снижает `parse_success_rate` ниже 70%
(слишком длинный JSON или модель игнорирует поле) → сделать `source_span` optional,
только warning-лог без hard fail.

**Post-ship replay:** запустить `scripts/eval_quiz_quality.py` на тех же scope.
Сравнить `critical_unsupported_rate` до и после.

**Outcome-status:** shipped-unvalidated (требует живого семпла)

---

### P0b: VLQR Eval Script (Ход 2)

**Problem:** нет baseline VLQR; нет воспроизводимого eval для смены промпта/модели.

**Evidence:** E1 — нет ни одного теста проверяющего semantic quality по символам.

**Proposed:** создать `scripts/eval_quiz_quality.py`:
- Принимает список scope (document/topic path)
- Для каждого scope: генерирует quiz через `generate_scoped_quiz_from_content()`
- Оценивает каждый вопрос по 8-пунктовой рубрике (ручная или LLM-proxy оценка)
- Выводит JSON отчёт: VLQR, fallback_rate, cognitive_label_match_rate, per-scope breakdown
- Опционально: CI job `.github/workflows/quiz_eval.yml`

**Files:**
- `scripts/eval_quiz_quality.py` (NEW)
- `docs/quiz_quality_eval_protocol.md` (NEW)

**DoD:**
- Скрипт запускается с `python scripts/eval_quiz_quality.py --scope-file eval_scopes.json`
- Выдаёт JSON с VLQR, fallback_rate, critical_unsupported_rate
- README строка добавлена (см. ниже)

**Metric contract:** VLQR baseline (wire-in-P0)

**Effort:** M (2 дня)

**Dependencies:** P0a (source_span для critical_unsupported_rate)

**Kill switch:** если eval дорог по времени (>30 мин на 15 вопросов) →
ограничить 5 вопросов × 3 повтора; если нет LLM endpoint → только структурные
метрики (parse_success, source_span_rate).

**Post-ship replay:** сравнить VLQR P0a vs baseline (до P0a).

**Outcome-status:** shipped-unvalidated

---

### P1: Confidence Tier для mastery writes

**Problem:** все quiz пути (validated + fallback + limited) одинаково обновляют mastery.

**Evidence:** E1 (код) + post-P0a data (source_span rate).

**Proposed:**
```python
class QuizConfidenceTier(Enum):
    VALIDATED = "validated"      # source_span ≥ 40, struct OK → mastery write
    LIMITED = "limited"          # source_span пустой, struct OK → save_quiz_result только
    FALLBACK_SKIPPED = "skipped" # is_fallback=True → нет DB write
```
Передавать tier из парсера через `evaluate_inline_quiz_answer` и `process_micro_quiz_outcome`.

**Files:**
- `app/fact_source_binding.py` — `apply_quiz_outcome_to_learner_state` сигнатура (+ tier param)
- `app/quiz_micro.py` — `process_micro_quiz_outcome`
- `app/quiz_scoped.py` — scoped quiz completion path (через `ui/scoped_quiz.py`)
- `app/quiz_service.py` — `evaluate_inline_quiz_answer`

**Effort:** M (2-3 дня)

**Dependencies:** P0a

---

### P2: Transfer Cognitive Level Classifier + Distractor Quality

**Problem:** difficulty=transfer в JSON ≠ реальный transfer вопрос;
дистракторы могут быть тривиальными.

**Proposed:**
- Детерминированный keyword classifier для transfer: наличие сценария/применения
  в тексте вопроса (список ключевых паттернов: «если», «в ситуации», «применить»,
  «что произойдёт», «каков будет» и т.д.)
- Добавить в `QUIZ_SCOPED_PROMPT`: «Для каждого неверного варианта добавь
  поле `distractor_reason`: одно предложение почему он неверен согласно тексту»
- VLQR breakdown по cognitive level в eval script

**Files:**
- `scripts/eval_quiz_quality.py` (extension)
- `app/prompts/_impl.py` (QUIZ_SCOPED_PROMPT distractor_reason)
- `app/quiz_scoped.py` (_normalize_scoped_questions, опциональное поле)

**Effort:** L (3-5 дней, требует живого семпла для калибровки классификатора)

---

## НЕ делать

- ❌ Не запускать LLM-судью на каждом пользовательском вопросе в runtime
  без доказанного эффекта и приемлемой latency
- ❌ Не использовать самооценку той же модели как единственное доказательство качества
- ❌ Не строить universal quiz quality framework — достаточно минимального contract
- ❌ Не добавлять новую DB-схему только ради eval — использовать quiz_results + metrics_db
- ❌ Не менять mastery/persistence до подтверждения причинной цепочки на живом семпле
- ❌ Не объявлять PAIN-04 (две линии производства) подтверждённой — mastery pipeline единый
- ❌ Не блокировать показ вопроса при fail content gate — показывать с confidence label
- ❌ Не делать попутный рефакторинг соседних модулей
- ❌ Не менять незакоммиченные файлы Route Policy

---

## README строка

```
| Quiz quality & mastery honesty | analysis: ✅ 2026-07-19 | implementation: ⬜ P0a+P0b planned | outcome: ⬜ pending live sample |
```

---

## Самодостаточный критический вывод

**Механизм:** промпт требует grounded вопросов, парсер проверяет только структуру.
Разрыв полный: semantic content gate отсутствует.

**Наблюдаемая ошибка:** fallback micro quiz (is_fallback=True) немедленно обновляет
mastery через тот же path что и live вопрос с LLM-генерацией. Это подтверждено кодом.

**Частота:** не доказана без живого семпла. Proxy estimate: VLQR ~45-55%
для scoped quiz; fallback_rate micro quiz — зависит от процента LLM-отказов.

**Пользовательский ущерб:** mastery и SR schedule, управляющие следующим
учебным шагом, могут содержать сигналы от структурно-валидных но content-invalid
вопросов. Масштаб ущерба: не доказан до living sample P0b.

**Минимальный fix (P0a):** source_span field + is_fallback flag + fallback не пишет mastery.
Это не требует LLM-судьи, не ломает local-first, не меняет архитектуру.
