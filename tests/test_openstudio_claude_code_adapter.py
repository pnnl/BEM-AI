from __future__ import annotations

import json
from pathlib import Path

import pytest

from examples.openstudio_ai.adapters.claude_code_adapter import (
    GENERATED_START,
    ClaudeCodeAdapter,
)
from examples.openstudio_ai.adapters.contracts import HostAdapterConfig


def _adapter() -> ClaudeCodeAdapter:
    return ClaudeCodeAdapter(
        HostAdapterConfig(
            host_name="claude_code",
            workspace_root=Path("examples/openstudio_ai").resolve(),
        )
    )


def test_claude_code_adapter_dry_run_generates_project_files(tmp_path: Path) -> None:
    result = _adapter().install(tmp_path, dry_run=True)

    assert result.dry_run is True
    assert {action.path.name for action in result.actions} == {".mcp.json", "CLAUDE.md"}
    assert not (tmp_path / ".mcp.json").exists()
    assert not (tmp_path / ".claude" / "CLAUDE.md").exists()


def test_claude_code_adapter_writes_mcp_config_and_instructions(tmp_path: Path) -> None:
    result = _adapter().install(tmp_path, dry_run=False)

    assert result.dry_run is False
    mcp_config = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    server = mcp_config["mcpServers"]["openstudio_ai"]
    assert server["args"][:3] == ["-m", "examples.openstudio_ai.openstudio_mcp.server", "--transport"]
    assert server["args"][3] == "stdio"
    assert "OPENSTUDIO_AI_ROOT" in server["env"]

    instructions = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert GENERATED_START in instructions
    assert "OpenStudio AI Harness" in instructions
    assert "openstudio_hvac_air_loop_creator.md" in instructions
    assert "HVAC_CHILD_SKILL_MANAGEMENT.md" not in instructions


def test_claude_code_adapter_preserves_other_mcp_servers(tmp_path: Path) -> None:
    existing = {"mcpServers": {"other": {"command": "node", "args": ["server.js"]}}}
    (tmp_path / ".mcp.json").write_text(json.dumps(existing), encoding="utf-8")

    _adapter().install(tmp_path, dry_run=False)

    mcp_config = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert "other" in mcp_config["mcpServers"]
    assert "openstudio_ai" in mcp_config["mcpServers"]


def test_claude_code_adapter_refuses_unmanaged_instructions_without_force(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "CLAUDE.md").write_text("# Existing project instructions\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        _adapter().install(tmp_path, dry_run=True)


def test_claude_code_adapter_exports_plugin_package(tmp_path: Path) -> None:
    result = _adapter().export_plugin(tmp_path, dry_run=False)

    plugin_dir = tmp_path / "openstudio-ai"
    assert result.marketplace_dir == tmp_path.resolve()
    assert result.plugin_dir == plugin_dir.resolve()
    assert (tmp_path / ".claude-plugin" / "marketplace.json").exists()
    assert (tmp_path / "INSTALL.md").exists()
    assert (plugin_dir / ".claude-plugin" / "plugin.json").exists()
    assert (plugin_dir / ".mcp.json").exists()
    assert (plugin_dir / "README.md").exists()
    assert (plugin_dir / "CONNECTORS.md").exists()
    assert (plugin_dir / "commands" / "add-vav-reheat.md").exists()
    assert (plugin_dir / "skills" / "openstudio-hvac-air-loop-creator" / "SKILL.md").exists()
    assert not (plugin_dir / "skills" / "HVAC-CHILD-SKILL-MANAGEMENT" / "SKILL.md").exists()
    assert (plugin_dir / "knowledge" / "openstudio_sdk_recipes.md").exists()
    assert (plugin_dir / "blackboard" / "schemas" / "workflow_state.schema.json").exists()

    plugin_json = json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert plugin_json["name"] == "openstudio-ai"
    mcp_json = json.loads((plugin_dir / ".mcp.json").read_text(encoding="utf-8"))
    assert "openstudio_ai" in mcp_json["mcpServers"]
    marketplace_json = json.loads((tmp_path / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert marketplace_json["name"] == "openstudio-ai-local"
    assert marketplace_json["plugins"][0]["source"] == "./openstudio-ai"


def test_claude_code_adapter_exports_command_frontmatter(tmp_path: Path) -> None:
    _adapter().export_plugin(tmp_path, dry_run=False)

    command = (tmp_path / "openstudio-ai" / "commands" / "add-vav-reheat.md").read_text(
        encoding="utf-8"
    )
    assert command.startswith("---\n")
    assert "name: add-vav-reheat\n" in command
    assert "description: Plan and execute a phased OpenStudio VAV reheat workflow.\n" in command
    assert "\n---\n\n# Add VAV Reheat" in command


def test_claude_code_adapter_exports_skill_frontmatter(tmp_path: Path) -> None:
    _adapter().export_plugin(tmp_path, dry_run=False)

    skill = (
        tmp_path
        / "openstudio-ai"
        / "skills"
        / "openstudio-hvac-air-loop-creator"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert skill.startswith("---\n")
    assert "name: openstudio_hvac_air_loop_creator\n" in skill
    assert "description: Create or confirm the parent AirLoopHVAC object" in skill
    assert "version: 0.1.0\n" in skill
    assert "\n---\n\n## Scope" in skill


def test_claude_code_adapter_export_plugin_dry_run_does_not_write(tmp_path: Path) -> None:
    result = _adapter().export_plugin(tmp_path, dry_run=True)

    assert result.dry_run is True
    assert result.marketplace_dir == tmp_path.resolve()
    assert result.plugin_dir == (tmp_path / "openstudio-ai").resolve()
    assert tmp_path / ".claude-plugin" / "marketplace.json" in result.files
    assert any(path.name == "plugin.json" for path in result.files)
    assert not (tmp_path / "openstudio-ai").exists()


def test_claude_code_adapter_export_plugin_requires_force_for_existing_dir(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "openstudio-ai"
    plugin_dir.mkdir()

    with pytest.raises(FileExistsError):
        _adapter().export_plugin(tmp_path, dry_run=False)
