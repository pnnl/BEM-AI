from __future__ import annotations

import pytest

from automa_ai.config.tools import ToolSpec
from automa_ai.tools import build_langchain_tools
from automa_ai.tools.run_command.config import RunCommandToolConfig
from automa_ai.tools.run_command.policy import (
    CommandPolicyViolationError,
    validate_command_policy,
)
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

    assert validate_command_policy(["rg", "-n", "AgentFactory", "."], config) == [
        "rg",
        "-n",
        "AgentFactory",
        ".",
    ]
    assert validate_command_policy(["rg", "--files", "-g", "*.py", "."], config) == [
        "rg",
        "--files",
        "-g",
        "*.py",
        ".",
    ]


def test_validate_command_policy_rejects_hidden_rg_search(tmp_path) -> None:
    config = RunCommandToolConfig.model_validate({"workspace_root": str(tmp_path)})

    with pytest.raises(CommandPolicyViolationError, match="Unsupported rg flag"):
        validate_command_policy(["rg", "--hidden", "SECRET", "."], config)


def test_validate_command_policy_allows_limited_git_forms(tmp_path) -> None:
    config = RunCommandToolConfig.model_validate({"workspace_root": str(tmp_path)})

    assert validate_command_policy(["git", "status", "--short"], config) == [
        "git",
        "status",
        "--short",
    ]
    assert validate_command_policy(["git", "diff", "--stat"], config) == [
        "git",
        "diff",
        "--stat",
    ]


def test_validate_command_policy_rejects_mutating_git_form(tmp_path) -> None:
    config = RunCommandToolConfig.model_validate({"workspace_root": str(tmp_path)})

    with pytest.raises(CommandPolicyViolationError, match="Only `git status`"):
        validate_command_policy(["git", "add", "."], config)
