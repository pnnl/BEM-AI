from __future__ import annotations

import shutil
import sys

import pytest
from pydantic import ValidationError

from automa_ai.config.tools import ToolSpec
from automa_ai.tools import build_langchain_tools
from automa_ai.tools.run_command.config import RunCommandToolConfig
from automa_ai.tools.run_command.policy import (
    CommandPolicyViolationError,
    validate_command_policy,
)
from automa_ai.tools.run_command.runner import LocalSubprocessRunner
from automa_ai.tools.run_command.tool import RunCommandTool


def test_registry_build_includes_run_command() -> None:
    tools = build_langchain_tools([ToolSpec(type="run_command", config={})])
    assert {tool.name for tool in tools} == {"run_command"}


@pytest.mark.asyncio
async def test_run_command_pwd_happy_path(tmp_path) -> None:
    tool = RunCommandTool(
        RunCommandToolConfig.model_validate({"workspace_root": str(tmp_path)})
    )
    result = await tool.invoke({"argv": ["pwd"]})

    assert result["success"] is True
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == str(tmp_path)


@pytest.mark.asyncio
async def test_run_command_cat_reads_workspace_file(tmp_path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("hello", encoding="utf-8")
    tool = RunCommandTool(
        RunCommandToolConfig.model_validate({"workspace_root": str(tmp_path)})
    )
    result = await tool.invoke({"argv": ["cat", "notes.txt"]})

    assert result["success"] is True
    assert result["stdout"] == "hello"


@pytest.mark.asyncio
async def test_run_command_rejects_unsupported_command(tmp_path) -> None:
    tool = RunCommandTool(
        RunCommandToolConfig.model_validate({"workspace_root": str(tmp_path)})
    )
    result = await tool.invoke({"argv": ["python3", "-V"]})

    assert result["success"] is False
    assert "not allowed" in result["stderr"]
    assert "command policy" in result["meta"]["warnings"][0].lower()


@pytest.mark.asyncio
async def test_run_command_rejects_parent_directory_escape(tmp_path) -> None:
    tool = RunCommandTool(
        RunCommandToolConfig.model_validate({"workspace_root": str(tmp_path)})
    )
    result = await tool.invoke({"argv": ["cat", "../outside.txt"]})

    assert result["success"] is False
    assert "workspace_root" in result["stderr"]


@pytest.mark.asyncio
async def test_run_command_rejects_blocked_sensitive_path(tmp_path) -> None:
    target = tmp_path / ".env"
    target.write_text("SECRET=1", encoding="utf-8")
    tool = RunCommandTool(
        RunCommandToolConfig.model_validate({"workspace_root": str(tmp_path)})
    )
    result = await tool.invoke({"argv": ["cat", ".env"]})

    assert result["success"] is False
    assert "blocked by policy" in result["stderr"]


def test_validate_command_policy_allows_curated_rg_forms(tmp_path) -> None:
    config = RunCommandToolConfig.model_validate({"workspace_root": str(tmp_path)})

    argv = validate_command_policy(["rg", "-n", "AgentFactory", "."], config)
    assert argv[:2] == [
        "rg",
        "-n",
    ]
    assert argv[-2:] == [
        "AgentFactory",
        ".",
    ]
    assert ["-g", "!.env"] == argv[2:4]

    files_argv = validate_command_policy(["rg", "--files", "-g", "*.py", "."], config)
    assert files_argv[:4] == [
        "rg",
        "--files",
        "-g",
        "*.py",
    ]
    assert files_argv[-1] == "."


def test_validate_command_policy_rejects_hidden_rg_search(tmp_path) -> None:
    config = RunCommandToolConfig.model_validate({"workspace_root": str(tmp_path)})

    with pytest.raises(CommandPolicyViolationError, match="Unsupported rg flag"):
        validate_command_policy(["rg", "--hidden", "SECRET", "."], config)


def test_validate_command_policy_allows_limited_git_forms(tmp_path) -> None:
    config = RunCommandToolConfig.model_validate({"workspace_root": str(tmp_path)})

    assert validate_command_policy(["git", "status", "--short"], config) == [
        "git",
        "--no-pager",
        "-c",
        "core.pager=cat",
        "-c",
        "diff.external=",
        "status",
        "--short",
    ]
    assert validate_command_policy(["git", "diff", "--stat"], config) == [
        "git",
        "--no-pager",
        "-c",
        "core.pager=cat",
        "-c",
        "diff.external=",
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--stat",
    ]
    assert validate_command_policy(["git", "diff", "--name-only"], config) == [
        "git",
        "--no-pager",
        "-c",
        "core.pager=cat",
        "-c",
        "diff.external=",
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--name-only",
    ]


def test_validate_command_policy_rejects_mutating_git_form(tmp_path) -> None:
    config = RunCommandToolConfig.model_validate({"workspace_root": str(tmp_path)})

    with pytest.raises(CommandPolicyViolationError, match="Only `git status`"):
        validate_command_policy(["git", "add", "."], config)


def test_validate_command_policy_allows_bounded_sed_form(tmp_path) -> None:
    config = RunCommandToolConfig.model_validate({"workspace_root": str(tmp_path)})
    target = tmp_path / "notes.txt"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")

    assert validate_command_policy(["sed", "-n", "1,2p", "notes.txt"], config) == [
        "sed",
        "-n",
        "1,2p",
        "notes.txt",
    ]


def test_validate_command_policy_rejects_unbounded_sed_form(tmp_path) -> None:
    config = RunCommandToolConfig.model_validate({"workspace_root": str(tmp_path)})

    with pytest.raises(CommandPolicyViolationError, match="Only `sed -n"):
        validate_command_policy(["sed", "s/one/two/g", "notes.txt"], config)


def test_run_command_config_rejects_unknown_runner_or_profile() -> None:
    with pytest.raises(ValidationError):
        RunCommandToolConfig.model_validate({"runner": "shell"})

    with pytest.raises(ValidationError):
        RunCommandToolConfig.model_validate({"profile": "write"})


@pytest.mark.asyncio
async def test_run_command_rg_excludes_blocked_files_even_with_broad_glob(
    tmp_path,
) -> None:
    if shutil.which("rg") is None:
        pytest.skip("ripgrep is required for rg execution coverage")

    (tmp_path / ".env").write_text("SECRET=hidden-root\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / ".env").write_text("SECRET=hidden-nested\n", encoding="utf-8")
    (tmp_path / "public.txt").write_text("SECRET=public\n", encoding="utf-8")

    tool = RunCommandTool(
        RunCommandToolConfig.model_validate({"workspace_root": str(tmp_path)})
    )
    result = await tool.invoke({"argv": ["rg", "-g", "*", "SECRET", "."]})

    assert result["success"] is True
    assert "public.txt" in result["stdout"]
    assert "hidden-root" not in result["stdout"]
    assert "hidden-nested" not in result["stdout"]


@pytest.mark.asyncio
async def test_run_command_timeout_returns_124_and_warning(tmp_path) -> None:
    runner = LocalSubprocessRunner(
        RunCommandToolConfig.model_validate(
            {"workspace_root": str(tmp_path), "timeout_s": 1}
        )
    )

    result = await runner.run([sys.executable, "-c", "import time; time.sleep(5)"])

    assert result.success is False
    assert result.exit_code == 124
    assert "timed out" in result.stderr.lower()
    assert any("terminated" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_run_command_truncates_stdout_and_stderr(tmp_path) -> None:
    runner = LocalSubprocessRunner(
        RunCommandToolConfig.model_validate(
            {
                "workspace_root": str(tmp_path),
                "max_stdout_chars": 100,
                "max_stderr_chars": 100,
            }
        )
    )

    result = await runner.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.stdout.write('x' * 150); "
                "sys.stderr.write('e' * 150)"
            ),
        ]
    )

    assert result.success is True
    assert len(result.stdout) == 100
    assert len(result.stderr) == 100
    assert any("stdout was truncated" in warning for warning in result.warnings)
    assert any("stderr was truncated" in warning for warning in result.warnings)
