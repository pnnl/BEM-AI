"""run_python default tool."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from automa_ai.tools.base import BaseDefaultTool
from automa_ai.tools.run_python.config import RunPythonToolConfig
from automa_ai.tools.run_python.policy import PolicyViolationError, validate_code_policy
from automa_ai.tools.run_python.runner import LocalSubprocessRunner
from automa_ai.telemetry import current_span_id, current_trace_id


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

        script_meta = _script_metadata(args.code)
        warnings = _script_size_warnings(script_meta, cfg)
        length_error = _script_length_error(script_meta, cfg)
        if length_error:
            warnings.append("Execution blocked by script length policy.")
            response = _tool_response(
                success=False,
                stdout="",
                stderr=length_error,
                exit_code=1,
                artifacts=[],
                runner=cfg.runner,
                warnings=warnings,
                script_meta=script_meta,
            )
            _record_failure_experience(
                cfg=cfg,
                args=args,
                response=response,
                stage="script_length_limit",
            )
            return response

        try:
            validate_code_policy(args.code, cfg)
        except PolicyViolationError as exc:
            warnings.append("Execution blocked by sandbox policy.")
            response = _tool_response(
                success=False,
                stdout="",
                stderr=str(exc),
                exit_code=1,
                artifacts=[],
                runner=cfg.runner,
                warnings=warnings,
                script_meta=script_meta,
            )
            _record_failure_experience(
                cfg=cfg,
                args=args,
                response=response,
                stage="policy",
            )
            return response

        runner = LocalSubprocessRunner(cfg)
        try:
            result = await runner.run(
                code=args.code,
                input_files=args.input_files,
                expected_outputs=args.expected_outputs,
            )
        except (ValueError, OSError) as exc:
            warnings.append("Execution failed before Python process start.")
            response = _tool_response(
                success=False,
                stdout="",
                stderr=str(exc),
                exit_code=1,
                artifacts=[],
                runner=cfg.runner,
                warnings=warnings,
                script_meta=script_meta,
            )
            _record_failure_experience(
                cfg=cfg,
                args=args,
                response=response,
                stage="pre_start",
            )
            return response

        warnings.extend(result.warnings)
        response = _tool_response(
            success=result.success,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            artifacts=result.artifacts,
            runner=cfg.runner,
            warnings=warnings,
            script_meta=script_meta,
        )
        if not result.success:
            _record_failure_experience(
                cfg=cfg,
                args=args,
                response=response,
                stage="runtime",
            )
        return response


def build_run_python_tool(config: dict[str, Any], _runtime_deps: Any) -> RunPythonTool:
    parsed = RunPythonToolConfig.model_validate(config)
    if parsed.runner != "local_subprocess":
        raise ValueError(f"Unsupported run_python runner: {parsed.runner}")
    return RunPythonTool(parsed)


def _tool_response(
    *,
    success: bool,
    stdout: str,
    stderr: str,
    exit_code: int,
    artifacts: list[dict[str, object]],
    runner: str,
    warnings: list[str],
    script_meta: dict[str, int],
) -> dict[str, Any]:
    return {
        "success": success,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "artifacts": artifacts,
        "meta": {
            "runner": runner,
            "warnings": warnings,
            "script": script_meta,
        },
    }


def _script_metadata(code: str) -> dict[str, int]:
    return {
        "line_count": len(code.splitlines()) or 1,
        "char_count": len(code),
    }


def _script_size_warnings(
    script_meta: dict[str, int],
    cfg: RunPythonToolConfig,
) -> list[str]:
    warnings: list[str] = []
    if cfg.warn_script_lines and script_meta["line_count"] > cfg.warn_script_lines:
        warnings.append(
            "Script is long "
            f"({script_meta['line_count']} lines > warn_script_lines "
            f"{cfg.warn_script_lines}); consider splitting into smaller phases."
        )
    if cfg.warn_script_chars and script_meta["char_count"] > cfg.warn_script_chars:
        warnings.append(
            "Script is large "
            f"({script_meta['char_count']} chars > warn_script_chars "
            f"{cfg.warn_script_chars}); consider splitting into smaller phases."
        )
    return warnings


def _script_length_error(
    script_meta: dict[str, int],
    cfg: RunPythonToolConfig,
) -> str | None:
    if cfg.max_script_lines and script_meta["line_count"] > cfg.max_script_lines:
        return (
            "Script length exceeds configured run_python limit: "
            f"{script_meta['line_count']} lines > max_script_lines "
            f"{cfg.max_script_lines}."
        )
    if cfg.max_script_chars and script_meta["char_count"] > cfg.max_script_chars:
        return (
            "Script length exceeds configured run_python limit: "
            f"{script_meta['char_count']} chars > max_script_chars "
            f"{cfg.max_script_chars}."
        )
    return None


def _record_failure_experience(
    *,
    cfg: RunPythonToolConfig,
    args: RunPythonInput,
    response: dict[str, Any],
    stage: str,
) -> None:
    if not cfg.failure_experience_path:
        return

    path = _resolve_failure_experience_path(cfg)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "trace_id": current_trace_id(),
        "span_id": current_span_id(),
        "success": False,
        "exit_code": response["exit_code"],
        "script": {
            **response["meta"]["script"],
            "code": args.code,
        },
        "stdout": response["stdout"],
        "stderr": response["stderr"],
        "warnings": response["meta"]["warnings"],
        "input_files": args.input_files,
        "expected_outputs": args.expected_outputs,
        "config": _failure_experience_config(cfg),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        # Failure experience logging is diagnostic and must never break tool use.
        return


def _resolve_failure_experience_path(cfg: RunPythonToolConfig) -> Path:
    assert cfg.failure_experience_path is not None
    path = Path(cfg.failure_experience_path).expanduser()
    if path.is_absolute():
        return path
    root = Path(cfg.workspace_root or ".").expanduser().resolve()
    return (root / path).resolve()


def _failure_experience_config(cfg: RunPythonToolConfig) -> dict[str, Any]:
    return {
        "runner": cfg.runner,
        "python_executable": cfg.python_executable,
        "timeout_s": cfg.timeout_s,
        "workspace_root": cfg.workspace_root,
        "allow_network": cfg.allow_network,
        "blocked_imports": cfg.blocked_imports,
        "warn_script_lines": cfg.warn_script_lines,
        "warn_script_chars": cfg.warn_script_chars,
        "max_script_lines": cfg.max_script_lines,
        "max_script_chars": cfg.max_script_chars,
    }
