"""Configuration for the run_command default tool."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RunCommandToolConfig(BaseModel):
    """Runtime configuration for curated command execution."""

    runner: str = "local_subprocess"
    profile: str = "exploration"
    timeout_s: int = Field(default=20, ge=1, le=300)
    max_stdout_chars: int = Field(default=20_000, ge=100, le=500_000)
    max_stderr_chars: int = Field(default=20_000, ge=100, le=500_000)
    workspace_root: str | None = None
    blocked_path_globs: list[str] = Field(
        default_factory=lambda: [
            ".env",
            ".env.*",
            "**/.env",
            "**/.env.*",
        ]
    )
