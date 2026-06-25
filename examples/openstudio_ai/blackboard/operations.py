from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def initialize_workflow(goal: str, *, workflow_id: str | None = None) -> dict[str, Any]:
    return {
        "workflow_id": workflow_id or str(uuid4()),
        "goal": goal,
        "status": "initialized",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "completed_steps": [],
        "pending_steps": [],
        "assumptions": [],
        "artifacts": [],
        "failures": [],
    }


def apply_state_patch(state: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    next_state = deepcopy(state)
    _deep_merge(next_state, patch)
    next_state["updated_at"] = datetime.now(timezone.utc).isoformat()
    return next_state


def mark_phase_complete(state: dict[str, Any], phase: str) -> dict[str, Any]:
    patch = {"completed_steps": sorted(set(state.get("completed_steps", [])) | {phase})}
    next_state = apply_state_patch(state, patch)
    next_state["pending_steps"] = [item for item in next_state.get("pending_steps", []) if item != phase]
    return next_state


def record_assumption(state: dict[str, Any], assumption: str) -> dict[str, Any]:
    assumptions = list(state.get("assumptions", []))
    assumptions.append(assumption)
    return apply_state_patch(state, {"assumptions": assumptions})


def record_artifact(state: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
    artifacts = list(state.get("artifacts", []))
    artifacts.append(artifact)
    return apply_state_patch(state, {"artifacts": artifacts})


def record_failure(state: dict[str, Any], failure: dict[str, Any]) -> dict[str, Any]:
    failures = list(state.get("failures", []))
    failures.append(failure)
    return apply_state_patch(state, {"failures": failures, "status": "needs_attention"})


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value

