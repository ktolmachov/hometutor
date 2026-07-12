"""HTTP API для истории прогонов агента (read-only).

Предоставляет доступ к сохранённым прогонам агента.
Санитайзинг чувствительных данных выполняется на уровне персистентности
(`app.user_state_agent_runs`).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.user_state_agent_runs import get_agent_run, list_agent_runs

router = APIRouter(tags=["agent"])


@router.get("/agent/runs")
def list_agent_runs_endpoint(limit: int = Query(20, ge=1, le=100)):
    """Возвращает список последних прогонов агента (без детализации шагов)."""
    return list_agent_runs(limit=limit)


@router.get("/agent/runs/{run_id}")
def get_agent_run_endpoint(run_id: str):
    """Возвращает полный прогон агента (включая шаги)."""
    run = get_agent_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="agent run not found")
    return run
