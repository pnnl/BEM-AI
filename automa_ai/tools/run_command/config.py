"""Configuration for the run_command default tool."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class RunCommandToolConfig(BaseModel):
    """Runtime configuration for curated command execution."""

    runner: Literal["local_subprocess"] = "local_subprocess"
    profile: Literal["exploration"] = "exploration"
    timeout_s: int = Field(default=20, ge=1, le=300)
    max_stdout_chars: int = Field(default=20_000, ge=100, le=500_000)
    max_stderr_chars: int = Field(default=20_000, ge=100, le=500_000)
    workspace_root: str = "."
    blocked_file_names: list[str] = Field(
        default_factory=lambda: [
            ".env",
            ".env.local",
            ".env.development",
            ".env.production",
            ".env.staging",
            ".env.test",
            ".envrc",
        ]
    )

    @model_validator(mode="after")
    def normalize_paths_and_policy(self) -> "RunCommandToolConfig":
        # Resolve once so policy validation and subprocess cwd use the same root.
        self.workspace_root = str(Path(self.workspace_root).resolve())
        for name in self.blocked_file_names:
            if not name or "/" in name or "\\" in name or "\x00" in name:
                raise ValueError(
                    "blocked_file_names must contain only plain file names."
                )
            if any(char in name for char in "*?[]{}"):
                raise ValueError(
                    "blocked_file_names must be exact file names, not glob patterns."
                )
        return self
