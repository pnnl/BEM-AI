from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_candidate_asset(root: str | Path, candidate: dict[str, Any]) -> Path:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    name = str(candidate["name"]).replace(" ", "_").lower()
    path = root_path / f"{name}.json"
    path.write_text(json.dumps(candidate, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path

