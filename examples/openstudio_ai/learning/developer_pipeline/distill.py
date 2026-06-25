from __future__ import annotations

from typing import Any


def distill_candidate_lesson(raw_event: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "candidate",
        "source_event_ids": [raw_event.get("event_id", "unknown")],
        "lesson_type": raw_event.get("event_type", "unknown"),
        "summary": raw_event.get("payload", {}).get("summary", ""),
        "evidence": raw_event.get("payload", {}),
    }

