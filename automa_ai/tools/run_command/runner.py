"""Execution runner for run_command."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from automa_ai.tools.run_command.config import RunCommandToolConfig


@dataclass
class RunCommandResult:
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    warnings: list[str]


class LocalSubprocessRunner:
    """Run validated argv directly without a shell."""

    def __init__(self, config: RunCommandToolConfig):
        self.config = config

    async def run(self, argv: list[str]) -> RunCommandResult:
        warnings: list[str] = []
        workspace_root = Path(self.config.workspace_root or os.getcwd()).resolve()
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(workspace_root),
            env=_build_subprocess_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                process.communicate(), timeout=self.config.timeout_s
            )
            exit_code = process.returncode
            success = exit_code == 0
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            stdout_b, stderr_b = b"", b"Execution timed out."
            exit_code = 124
            success = False
            warnings.append("Execution timed out and the process was terminated.")

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        stdout = _truncate(stdout, self.config.max_stdout_chars, "stdout", warnings)
        stderr = _truncate(stderr, self.config.max_stderr_chars, "stderr", warnings)

        return RunCommandResult(
            success=success,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            warnings=warnings,
        )


def _build_subprocess_env() -> dict[str, str]:
    allowed = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TMP",
        "TEMP",
        "HOME",
        "USERPROFILE",
        "LANG",
        "LC_ALL",
    }
    env: dict[str, str] = {}
    for key in allowed:
        value = os.environ.get(key)
        if value:
            env[key] = value
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _truncate(value: str, max_chars: int, label: str, warnings: list[str]) -> str:
    if len(value) <= max_chars:
        return value
    warnings.append(f"{label} was truncated to {max_chars} characters.")
    return value[:max_chars]
