"""run_python default tool."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from automa_ai.tools.base import BaseDefaultTool
from automa_ai.tools.run_python.config import RunPythonToolConfig
from automa_ai.tools.run_python.policy import PolicyViolationError, validate_code_policy
from automa_ai.tools.run_python.runner import LocalSubprocessRunner


class RunPythonInput(BaseModel):
    code: str = Field(min_length=1)
    input_files: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    timeout_s: int | None = Field(default=None, ge=1, le=300)


class RunPythonTool(BaseDefaultTool):
    type = "run_python"

    def __init__(self, config: RunPythonToolConfig):
        self.config = config

    @property
    def args_schema(self) -> type[BaseModel]:
        return RunPythonInput

    @property
    def description(self) -> str:
        return (
            "Execute Python for calculations, structured-data parsing, charts/tables, "
            "file transformations, and simulation preparation logic using a best-effort "
            "sandbox policy. Not for untrusted code."
        )

    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        args = RunPythonInput.model_validate(payload)
        if args.timeout_s is not None:
            timeout_s = min(args.timeout_s, self.config.timeout_s)
            cfg = self.config.model_copy(update={"timeout_s": timeout_s})
        else:
            cfg = self.config

        try:
            validate_code_policy(args.code, cfg)
        except PolicyViolationError as exc:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(exc),
                "exit_code": 1,
                "artifacts": [],
                "meta": {
                    "runner": cfg.runner,
                    "warnings": ["Execution blocked by sandbox policy."],
                },
            }

        runner = LocalSubprocessRunner(cfg)
        result = await runner.run(
            code=args.code,
            input_files=args.input_files,
            expected_outputs=args.expected_outputs,
        )
        return {
            "success": result.success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "artifacts": result.artifacts,
            "meta": {
                "runner": cfg.runner,
                "warnings": result.warnings,
            },
        }


def build_run_python_tool(config: dict[str, Any], _runtime_deps: Any) -> RunPythonTool:
    parsed = RunPythonToolConfig.model_validate(config)
    if not parsed.enabled:
        raise ValueError("run_python tool is disabled by configuration.")
    if parsed.runner != "local_subprocess":
        raise ValueError(f"Unsupported run_python runner: {parsed.runner}")
    return RunPythonTool(parsed)
