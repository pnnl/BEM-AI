from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def enqueue_for_review(queue_dir: str | Path, candidate: dict[str, Any]) -> Path:
    root = Path(queue_dir)
    root.mkdir(parents=True, exist_ok=True)
    candidate_id = candidate.get("candidate_id") or candidate.get("lesson_id") or "candidate"
    path = root / f"{candidate_id}.json"
    path.write_text(json.dumps(candidate, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path

