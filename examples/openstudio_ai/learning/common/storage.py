from __future__ import annotations

import json
from pathlib import Path

from examples.openstudio_ai.learning.common.events import LearningEvent


def append_learning_event(path: str | Path, event: LearningEvent) -> None:
    event_path = Path(path)
    event_path.parent.mkdir(parents=True, exist_ok=True)
    with event_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event.to_jsonable(), ensure_ascii=True) + "\n")

