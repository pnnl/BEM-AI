"""run_command default tool."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from automa_ai.tools.base import BaseDefaultTool
from automa_ai.tools.run_command.config import RunCommandToolConfig
from automa_ai.tools.run_command.policy import (
    CommandPolicyViolationError,
    validate_command_policy,
)
from automa_ai.tools.run_command.runner import LocalSubprocessRunner


class RunCommandInput(BaseModel):
    argv: list[str] = Field(min_length=1)
    timeout_s: int | None = Field(default=None, ge=1, le=300)


class RunCommandTool(BaseDefaultTool):
    type = "run_command"

    def __init__(self, config: RunCommandToolConfig):
        self.config = config

    @property
    def args_schema(self) -> type[BaseModel]:
        return RunCommandInput

    @property
    def description(self) -> str:
        return (
            "Run curated local commands for codebase exploration using argv only. "
            "The exploration profile allows safe read-oriented commands such as "
            "pwd, ls, rg, cat, sed, head, tail, and limited git status/diff forms."
        )

    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        args = RunCommandInput.model_validate(payload)
        if args.timeout_s is not None:
            timeout_s = min(args.timeout_s, self.config.timeout_s)
            cfg = self.config.model_copy(update={"timeout_s": timeout_s})
        else:
            cfg = self.config

        try:
            argv = validate_command_policy(args.argv, cfg)
        except CommandPolicyViolationError as exc:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(exc),
                "exit_code": 1,
                "meta": {
                    "runner": cfg.runner,
                    "profile": cfg.profile,
                    "warnings": ["Execution blocked by command policy."],
                },
            }

        runner = LocalSubprocessRunner(cfg)
        try:
            result = await runner.run(argv)
        except (FileNotFoundError, NotADirectoryError, PermissionError, OSError) as exc:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(exc),
                "exit_code": 1,
                "meta": {
                    "runner": cfg.runner,
                    "profile": cfg.profile,
                    "warnings": ["Execution failed before process start."],
                },
            }

        return {
            "success": result.success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "meta": {
                "runner": cfg.runner,
                "profile": cfg.profile,
                "warnings": result.warnings,
            },
        }


def build_run_command_tool(config: dict[str, Any], runtime_deps: Any) -> RunCommandTool:
    _ = runtime_deps
    parsed = RunCommandToolConfig.model_validate(config)
    return RunCommandTool(parsed)
