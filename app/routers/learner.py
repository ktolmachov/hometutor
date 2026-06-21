"""HTTP API для сохранённого снимка learner goal (E24-B, SQLite ``user_state``)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api_models import LearnerGoalContextOut, LearnerGoalSnapshotOut
from app.api_requests import LearnerGoalSnapshotPutRequest
from app.user_state import (
    clear_learner_goal_snapshot,
    get_learner_goal_snapshot,
    learner_goal_snapshot_api_empty,
    upsert_learner_goal_snapshot,
)

router = APIRouter(tags=["learner"])


def _snapshot_out(data: dict) -> LearnerGoalSnapshotOut:
    return LearnerGoalSnapshotOut(
        schema_version=data.get("schema_version"),
        updated_at=data.get("updated_at"),
        goal_context=LearnerGoalContextOut(**data["goal_context"])
        if data.get("goal_context")
        else None,
    )


@router.get("/learner/goal-snapshot", response_model=LearnerGoalSnapshotOut)
def get_learner_goal_snapshot_endpoint() -> LearnerGoalSnapshotOut:
    raw = get_learner_goal_snapshot()
    if raw is None:
        return LearnerGoalSnapshotOut(**learner_goal_snapshot_api_empty())
    return _snapshot_out(raw)


@router.put("/learner/goal-snapshot", response_model=LearnerGoalSnapshotOut)
def put_learner_goal_snapshot_endpoint(body: LearnerGoalSnapshotPutRequest) -> LearnerGoalSnapshotOut:
    payload = body.model_dump()
    data = upsert_learner_goal_snapshot(**payload)
    return _snapshot_out(data)


@router.delete("/learner/goal-snapshot")
def delete_learner_goal_snapshot_endpoint() -> dict[str, str]:
    clear_learner_goal_snapshot()
    return {"status": "cleared"}
