from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class HarnessAssets:
    root: Path
    prompt_contracts: list[Path]
    skill_files: list[Path]
    mcp_entrypoint: Path
    blackboard_schema: Path
    learning_event_log: Path
    knowledge_roots: list[Path] = field(default_factory=list)
    sdk_index_roots: list[Path] = field(default_factory=list)

