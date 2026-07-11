# OpenNotebook → HomeTutor Bridge v1

## Цель

Open Notebook удобен как workspace: источники, быстрые summary, первичный research, notebook-логика.

`hometutor` должен оставаться строгим RAG engine: stable citations, source-id integrity, refusal, quiz, gates.

Поэтому интеграция делается через стабильный `source pack`:

```text
manifest.json + sources/ + derived/
```

## Контракт pack-а

```text
open_notebook_export_.../
  manifest.json
  sources/
    *.md
    *.txt
    *.pdf
  derived/
    *.md
```

`sources/` — первичные источники.  
`derived/` — AI-сгенерированные материалы, summary, заметки. По умолчанию не являются authoritative.

## Правила citation policy

```text
authoritative:
  можно использовать для product-grade ответов и citations

derived_non_authoritative:
  можно использовать как черновик/контекст для человека,
  но нельзя цитировать как первичный источник фактов
```

## Stable source_id

Формат:

```text
onb:{notebook_slug}:{source_slug}:{sha256_8}
```

Пример:

```text
onb:local-ai-runtime-notes:local-llm-runtime-notes:8f31a9c2
```

## Почему не SurrealDB

Open Notebook internal DB — не контракт. Его структура может меняться. Чтение SurrealDB напрямую создаёт tight coupling.

Правильный контракт:

```text
exported files + manifest -> import -> hometutor canonical source registry
```

## Почему не общая vector DB

Open Notebook и hometutor могут иметь разные chunking/retrieval assumptions.

На MVP этапе:

```text
Open Notebook: свой storage / workspace
hometutor: свой Chroma/BM25/reranker/gates
```

Общий только model runtime: llama.cpp/LiteLLM.

## Bridge Gate

`OpenNotebookToHomeTutorGate-v1` проверяет:

1. manifest JSON parse;
2. SHA256;
3. authoritative source count;
4. derived sources are not authoritative;
5. stable source_id;
6. canonical files exist;
7. no transient Open Notebook source ids leak;
8. exact evidence is findable;
9. refusal case has no evidence in sources.

## Рекомендуемый workflow

```text
Open Notebook:
  load sources -> explore -> summarize -> select useful sources

Bridge:
  export pack -> import_open_notebook_pack.py -> run gate

hometutor:
  ingest -> strict RAG -> citations -> quiz -> product baseline
```
