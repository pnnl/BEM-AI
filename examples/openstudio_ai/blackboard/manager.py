from __future__ import annotations

from pathlib import Path
from typing import Any

from examples.openstudio_ai.blackboard.operations import apply_state_patch, initialize_workflow
from examples.openstudio_ai.blackboard.store import JsonBlackboardStore


class BlackboardManager:
    def __init__(self, state_root: str | Path):
        self.store = JsonBlackboardStore(state_root)

    def initialize(self, goal: str) -> dict[str, Any]:
        state = initialize_workflow(goal)
        self.store.write(state)
        return state

    def apply_patch(self, workflow_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        state = self.store.read(workflow_id)
        next_state = apply_state_patch(state, patch)
        self.store.write(next_state)
        return next_state

