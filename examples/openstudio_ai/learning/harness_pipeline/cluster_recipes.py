from __future__ import annotations

from collections import defaultdict
from typing import Any


def group_scripts_by_intent(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get("intent", "unknown"))].append(record)
    return dict(grouped)

