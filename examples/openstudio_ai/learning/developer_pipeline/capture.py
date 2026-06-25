from __future__ import annotations

from pathlib import Path
from typing import Any

from examples.openstudio_ai.learning.common.events import LearningEvent
from examples.openstudio_ai.learning.common.storage import append_learning_event


def capture_developer_event(
    event_log: str | Path,
    event_type: str,
    payload: dict[str, Any],
    *,
    workflow_id: str | None = None,
) -> LearningEvent:
    event = LearningEvent(
        event_type=event_type,
        source="developer_pipeline",
        payload=payload,
        workflow_id=workflow_id,
    )
    append_learning_event(event_log, event)
    return event

