# hometutor — Product

Приложение адаптивного обучения: FastAPI + Streamlit + Chroma + LangChain + Anthropic.
Этот репозиторий содержит ТОЛЬКО рантайм продукта. Инструменты разработки и
документация процесса — в репозитории `hometutor-studio`.

## Запуск (локально)

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # заполнить ключи
python ingest.py                # индексация demo_data/ в chroma_db/
python main.py                  # FastAPI на :8000
streamlit run app/ui/main.py    # UI
```

## Docker

```bash
docker compose up
```

См. `docs/quickstart.md`, `docs/architecture.md`, `docs/api_reference.md`.
