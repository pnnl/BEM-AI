from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AssetLineage:
    source_event_ids: list[str]
    reviewer: str | None = None
    eval_case_ids: list[str] = field(default_factory=list)
    promotion_target: str | None = None

