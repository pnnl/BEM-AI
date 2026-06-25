from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def snapshot_workflow(state: dict[str, Any], snapshot_root: str | Path) -> Path:
    root = Path(snapshot_root)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = root / f"{state['workflow_id']}_{stamp}.json"
    path.write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path

