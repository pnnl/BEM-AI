from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HarnessPaths:
    root: Path
    prompts_dir: Path
    skills_dir: Path
    mcp_dir: Path
    knowledge_dir: Path
    state_dir: Path


@dataclass(frozen=True)
class HostAdapterConfig:
    host_name: str
    workspace_root: Path
    enable_learning_capture: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HostLaunchPlan:
    host_name: str
    system_prompt_files: list[Path]
    skill_paths: list[Path]
    mcp_entrypoint: Path
    blackboard_schema: Path
    learning_event_log: Path
    notes: list[str] = field(default_factory=list)

