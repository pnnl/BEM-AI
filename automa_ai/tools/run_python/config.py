"""Configuration for the run_python default tool."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RunPythonToolConfig(BaseModel):
    """Runtime configuration for the Python execution tool."""

    runner: str = "local_subprocess"
    python_executable: str = "python"
    timeout_s: int = Field(default=20, ge=1, le=300)
    max_stdout_chars: int = Field(default=20_000, ge=100, le=500_000)
    max_stderr_chars: int = Field(default=20_000, ge=100, le=500_000)
    workspace_root: str | None = None
    # This toggles import-level checks only and is not runtime network enforcement.
    allow_network: bool = False
    allowed_imports: list[str] = Field(default_factory=list)
    blocked_imports: list[str] = Field(
        default_factory=lambda: [
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "ctypes",
        ]
    )
    max_artifacts: int = Field(default=10, ge=0, le=100)
    max_artifact_bytes: int = Field(default=5_000_000, ge=1_000, le=100_000_000)
    warn_script_lines: int | None = Field(default=120, ge=1)
    warn_script_chars: int | None = Field(default=None, ge=1)
    max_script_lines: int | None = Field(default=None, ge=1)
    max_script_chars: int | None = Field(default=None, ge=1)
    failure_experience_path: str | None = None
