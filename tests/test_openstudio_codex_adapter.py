from __future__ import annotations

import json
from pathlib import Path

import pytest

from examples.openstudio_ai.adapters.codex_adapter import CodexAdapter
from examples.openstudio_ai.adapters.contracts import HostAdapterConfig


def _adapter() -> CodexAdapter:
    return CodexAdapter(
        HostAdapterConfig(
            host_name="codex",
            workspace_root=Path("examples/openstudio_ai").resolve(),
        )
    )


def test_codex_adapter_export_plugin_dry_run_does_not_write(tmp_path: Path) -> None:
    result = _adapter().export_plugin(tmp_path, dry_run=True)

    assert result.dry_run is True
    assert result.marketplace_path == (tmp_path / ".agents" / "plugins" / "marketplace.json").resolve()
    assert result.plugin_dir == (tmp_path / "plugins" / "openstudio-ai").resolve()
    assert result.marketplace_path in result.files
    assert not result.plugin_dir.exists()


def test_codex_adapter_exports_plugin_package(tmp_path: Path) -> None:
    result = _adapter().export_plugin(tmp_path, dry_run=False)

    plugin_dir = tmp_path / "plugins" / "openstudio-ai"
    assert result.plugin_dir == plugin_dir.resolve()
    assert (tmp_path / ".agents" / "plugins" / "marketplace.json").exists()
    assert (tmp_path / "INSTALL.md").exists()
    assert (plugin_dir / ".codex-plugin" / "plugin.json").exists()
    assert (plugin_dir / ".mcp.json").exists()
    assert (plugin_dir / "README.md").exists()
    assert (plugin_dir / "CONNECTORS.md").exists()
    assert (plugin_dir / "skills" / "openstudio-hvac-air-loop-creator" / "SKILL.md").exists()
    assert not (plugin_dir / "skills" / "HVAC-CHILD-SKILL-MANAGEMENT" / "SKILL.md").exists()
    assert (plugin_dir / "knowledge" / "openstudio_sdk_recipes.md").exists()
    assert (plugin_dir / "blackboard" / "schemas" / "workflow_state.schema.json").exists()
    assert (plugin_dir / "learning" / "README.md").exists()
    assert (plugin_dir / "learning" / "schemas" / "candidate_measure.schema.json").exists()
    assert (plugin_dir / "learning" / "candidates" / ".gitkeep").exists()
    install_doc = (tmp_path / "INSTALL.md").read_text(encoding="utf-8")
    assert f"codex plugin marketplace add {tmp_path}" in install_doc


def test_codex_adapter_exports_valid_manifest_and_marketplace(tmp_path: Path) -> None:
    _adapter().export_plugin(tmp_path, dry_run=False)

    plugin_dir = tmp_path / "plugins" / "openstudio-ai"
    plugin_json = json.loads((plugin_dir / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert plugin_json["name"] == "openstudio-ai"
    assert plugin_json["skills"] == "./skills/"
    assert plugin_json["mcpServers"] == "./.mcp.json"
    assert plugin_json["interface"]["displayName"] == "OpenStudio AI"
    assert plugin_json["interface"]["defaultPrompt"]

    marketplace_json = json.loads(
        (tmp_path / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
    )
    assert marketplace_json["name"] == "openstudio-ai-local"
    assert marketplace_json["plugins"][0]["source"]["path"] == "./plugins/openstudio-ai"
    assert marketplace_json["plugins"][0]["policy"]["installation"] == "AVAILABLE"


def test_codex_adapter_exports_mcp_config(tmp_path: Path) -> None:
    _adapter().export_plugin(tmp_path, dry_run=False)

    mcp_json = json.loads(
        (tmp_path / "plugins" / "openstudio-ai" / ".mcp.json").read_text(encoding="utf-8")
    )
    server = mcp_json["mcpServers"]["openstudio_ai"]
    assert server["args"][:3] == ["-m", "examples.openstudio_ai.openstudio_mcp.server", "--transport"]
    assert server["args"][3] == "stdio"
    assert "OPENSTUDIO_AI_ROOT" in server["env"]


def test_codex_adapter_export_requires_force_for_existing_plugin(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins" / "openstudio-ai"
    plugin_dir.mkdir(parents=True)

    with pytest.raises(FileExistsError):
        _adapter().export_plugin(tmp_path, dry_run=False)
