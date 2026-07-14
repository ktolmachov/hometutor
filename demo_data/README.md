# Demo corpus для публичного деплоя

Открытые учебные markdown-фрагменты (RAG, Chroma, hybrid search, SRS, guardrails,
Python basics) и встроенный self-demo курс `uploads/hometutor_101/`.
Используются для:

- Hugging Face Spaces (`deploy/hf-spaces/`)
- `eval/eval_dataset.json` и `scripts/run_defense_eval.py`
- Прединдекс `demo_chroma_db/` (`scripts/build_demo_chroma.py`)

`uploads/hometutor_101/` — полноценный demo course pack: лекции, smart-конспекты,
`*.media.json` и короткие MP4 для панели «🎞 Все видео урока» в Living Konspekt.
В pack не кладутся `*.silent.mp4`-дубликаты.

Не заменяют личный корпус в `data/` для local-first сценария.
