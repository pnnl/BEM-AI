"""Execution runner for run_python."""

from __future__ import annotations

import asyncio
import mimetypes
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from automa_ai.tools.run_python.config import RunPythonToolConfig


@dataclass
class RunResult:
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    artifacts: list[dict[str, object]]
    warnings: list[str]


class LocalSubprocessRunner:
    """Run Python in a temporary workspace using subprocess_exec only."""

    def __init__(self, config: RunPythonToolConfig):
        self.config = config

    async def run(
        self,
        code: str,
        input_files: list[str],
        expected_outputs: list[str],
    ) -> RunResult:
        warnings: list[str] = []
        workspace_root = Path(self.config.workspace_root or os.getcwd()).resolve()

        with tempfile.TemporaryDirectory(prefix="run_python_") as tmp:
            tmp_root = Path(tmp)
            copied_inputs: set[str] = set()
            for rel_path in input_files:
                src = _resolve_workspace_file(workspace_root, rel_path)
                dest = _resolve_temp_file(tmp_root, rel_path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                copied_inputs.add(str(dest.relative_to(tmp_root)))

            script = tmp_root / "__run_python__.py"
            script.write_text(code, encoding="utf-8")
            env = _build_subprocess_env()

            process = await asyncio.create_subprocess_exec(
                self.config.python_executable,
                "-I",
                "-B",
                str(script.name),
                cwd=str(tmp_root),
                env=env,
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

            artifacts = _collect_artifacts(
                root=tmp_root,
                expected_outputs=expected_outputs,
                max_artifacts=self.config.max_artifacts,
                max_artifact_bytes=self.config.max_artifact_bytes,
                warnings=warnings,
                excluded_paths=copied_inputs,
            )

            return RunResult(
                success=success,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                artifacts=artifacts,
                warnings=warnings,
            )


def _collect_artifacts(
    root: Path,
    expected_outputs: list[str],
    max_artifacts: int,
    max_artifact_bytes: int,
    warnings: list[str],
    excluded_paths: set[str],
) -> list[dict[str, object]]:
    if max_artifacts == 0:
        return []

    results: list[dict[str, object]] = []
    candidates: list[Path] = []

    if expected_outputs:
        for rel in expected_outputs:
            path = _resolve_temp_file(root, rel)
            if path.exists() and path.is_file():
                candidates.append(path)
            else:
                warnings.append(f"Expected output was not found: {rel}")
    else:
        for path in root.rglob("*"):
            if not path.is_file() or path.name == "__run_python__.py":
                continue
            rel_path = str(path.relative_to(root))
            if rel_path in excluded_paths:
                continue
            candidates.append(path)

    for path in candidates:
        if len(results) >= max_artifacts:
            warnings.append("Artifact limit reached; some files were not returned.")
            break
        size = path.stat().st_size
        if size > max_artifact_bytes:
            warnings.append(f"Artifact exceeds max_artifact_bytes and was skipped: {path}")
            continue
        rel_path = str(path.relative_to(root))
        mime_type, _ = mimetypes.guess_type(path.name)
        results.append(
            {
                "path": rel_path,
                "size_bytes": size,
                "mime_type": mime_type,
            }
        )
    return results


def _resolve_workspace_file(workspace_root: Path, rel_path: str) -> Path:
    path = (workspace_root / rel_path).resolve()
    if workspace_root not in path.parents and path != workspace_root:
        raise ValueError(f"Input path must stay within workspace_root: {rel_path}")
    if not path.exists() or not path.is_file():
        raise ValueError(f"Input file does not exist: {rel_path}")
    return path


def _resolve_temp_file(temp_root: Path, rel_path: str) -> Path:
    path = (temp_root / rel_path).resolve()
    if temp_root not in path.parents and path != temp_root:
        raise ValueError(f"Path must stay within temporary workspace: {rel_path}")
    return path


def _truncate(value: str, max_chars: int, label: str, warnings: list[str]) -> str:
    if len(value) <= max_chars:
        return value
    warnings.append(f"{label} was truncated to {max_chars} characters.")
    return value[:max_chars]


def _build_subprocess_env() -> dict[str, str]:
    """Build a minimal but platform-safe environment for Python subprocesses."""
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
    env["PYTHONNOUSERSITE"] = "1"
    env["MPLBACKEND"] = "Agg"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env
