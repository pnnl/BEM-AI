from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonBlackboardStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, workflow_id: str) -> Path:
        return self.root / f"{workflow_id}.json"

    def read(self, workflow_id: str) -> dict[str, Any]:
        return json.loads(self.path_for(workflow_id).read_text(encoding="utf-8"))

    def write(self, state: dict[str, Any]) -> Path:
        workflow_id = str(state["workflow_id"])
        path = self.path_for(workflow_id)
        path.write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        return path

