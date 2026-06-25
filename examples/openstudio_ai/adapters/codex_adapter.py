from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from examples.openstudio_ai.adapters.base import OpenStudioAiHostAdapter
from examples.openstudio_ai.adapters.contracts import HostAdapterConfig, HostLaunchPlan
from examples.openstudio_ai.harness.registry import discover_harness_assets


DEFAULT_PLUGIN_NAME = "openstudio-ai"
MARKETPLACE_NAME = "openstudio-ai-local"
SERVER_NAME = "openstudio_ai"


@dataclass(frozen=True)
class CodexPluginExportResult:
    """Result for exporting a Codex plugin package and local marketplace."""

    dry_run: bool
    marketplace_path: Path
    plugin_dir: Path
    files: list[Path]


class CodexAdapter(OpenStudioAiHostAdapter):
    """Adapter contract for exporting OpenStudio AI into Codex plugin format."""

    def build_launch_plan(self) -> HostLaunchPlan:
        """Resolve the host-facing assets from the OpenStudio AI harness registry."""
        assets = discover_harness_assets(self.config.workspace_root)
        return HostLaunchPlan(
            host_name="codex",
            system_prompt_files=assets.prompt_contracts,
            skill_paths=assets.skill_files,
            mcp_entrypoint=assets.mcp_entrypoint,
            blackboard_schema=assets.blackboard_schema,
            learning_event_log=assets.learning_event_log,
            notes=["Export skills, MCP config, knowledge, and instructions as a Codex plugin."],
        )

    def export_plugin(
        self,
        output_dir: Path,
        *,
        plugin_name: str = DEFAULT_PLUGIN_NAME,
        dry_run: bool = True,
        force: bool = False,
    ) -> CodexPluginExportResult:
        """Export a Codex plugin plus a repo-local marketplace manifest."""
        workspace_root = self.config.workspace_root.resolve()
        export_root = output_dir.resolve()
        plugin_dir = export_root / "plugins" / plugin_name
        marketplace_path = export_root / ".agents" / "plugins" / "marketplace.json"
        plan = self.build_launch_plan()
        files = _planned_export_files(export_root, plugin_dir, marketplace_path, plan, workspace_root)

        if dry_run:
            return CodexPluginExportResult(
                dry_run=True,
                marketplace_path=marketplace_path,
                plugin_dir=plugin_dir,
                files=files,
            )

        if plugin_dir.exists():
            if not force:
                raise FileExistsError(f"{plugin_dir} already exists. Use --force to replace it.")
            shutil.rmtree(plugin_dir)

        marketplace_path.parent.mkdir(parents=True, exist_ok=True)
        marketplace_path.write_text(_render_marketplace_json(plugin_name), encoding="utf-8")
        (export_root / "INSTALL.md").write_text(
            _render_install_doc(export_root, marketplace_path, plugin_name),
            encoding="utf-8",
        )
        _write_plugin_package(plugin_dir, plan, workspace_root)
        return CodexPluginExportResult(
            dry_run=False,
            marketplace_path=marketplace_path,
            plugin_dir=plugin_dir,
            files=files,
        )


def _planned_export_files(
    export_root: Path,
    plugin_dir: Path,
    marketplace_path: Path,
    plan: HostLaunchPlan,
    workspace_root: Path,
) -> list[Path]:
    """Return the files that `export_plugin` would create."""
    files = [
        marketplace_path,
        export_root / "INSTALL.md",
        plugin_dir / ".codex-plugin" / "plugin.json",
        plugin_dir / ".mcp.json",
        plugin_dir / "README.md",
        plugin_dir / "CONNECTORS.md",
        plugin_dir / "blackboard" / "schemas" / plan.blackboard_schema.name,
    ]
    files.extend(plugin_dir / "instructions" / path.name for path in plan.system_prompt_files)
    files.extend(plugin_dir / "skills" / _skill_dir_name(path) / "SKILL.md" for path in plan.skill_paths)

    knowledge_root = workspace_root / "knowledge"
    if knowledge_root.exists():
        files.extend(
            plugin_dir / "knowledge" / path.relative_to(knowledge_root)
            for path in knowledge_root.rglob("*")
            if path.is_file()
        )
    return sorted(files)


def _write_plugin_package(plugin_dir: Path, plan: HostLaunchPlan, workspace_root: Path) -> None:
    """Materialize the Codex plugin package on disk."""
    (plugin_dir / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "skills").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "instructions").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "blackboard" / "schemas").mkdir(parents=True, exist_ok=True)

    (plugin_dir / ".codex-plugin" / "plugin.json").write_text(
        _render_plugin_json(),
        encoding="utf-8",
    )
    (plugin_dir / ".mcp.json").write_text(_render_mcp_config(workspace_root), encoding="utf-8")
    (plugin_dir / "README.md").write_text(_render_plugin_readme(plan), encoding="utf-8")
    (plugin_dir / "CONNECTORS.md").write_text(_render_connectors_doc(workspace_root), encoding="utf-8")

    for prompt in plan.system_prompt_files:
        shutil.copy2(prompt, plugin_dir / "instructions" / prompt.name)

    for skill in plan.skill_paths:
        target_dir = plugin_dir / "skills" / _skill_dir_name(skill)
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill, target_dir / "SKILL.md")

    shutil.copy2(plan.blackboard_schema, plugin_dir / "blackboard" / "schemas" / plan.blackboard_schema.name)

    knowledge_root = workspace_root / "knowledge"
    if knowledge_root.exists():
        shutil.copytree(knowledge_root, plugin_dir / "knowledge")


def _render_plugin_json() -> str:
    """Render Codex `.codex-plugin/plugin.json` with validation-required metadata."""
    return json.dumps(
        {
            "name": DEFAULT_PLUGIN_NAME,
            "version": "0.1.0",
            "description": (
                "OpenStudio AI harness for OpenStudio model editing, simulation, "
                "results, SDK lookup, and reusable workflow skills."
            ),
            "author": {
                "name": "OpenStudio AI",
            },
            "license": "BSD-3-Clause",
            "keywords": ["openstudio", "building-energy-modeling", "mcp", "simulation"],
            "skills": "./skills/",
            "mcpServers": "./.mcp.json",
            "interface": {
                "displayName": "OpenStudio AI",
                "shortDescription": "OpenStudio modeling, simulation, SDK lookup, and workflow skills.",
                "longDescription": (
                    "OpenStudio AI packages MCP tools, reusable skills, reviewed knowledge, "
                    "and blackboard contracts for building-energy modeling workflows."
                ),
                "developerName": "OpenStudio AI",
                "category": "Engineering",
                "capabilities": ["MCP", "Skills", "Workflow Automation"],
                "defaultPrompt": [
                    "Inspect this OpenStudio model.",
                    "Add a VAV reheat system.",
                    "Run simulation and summarize results.",
                ],
                "brandColor": "#2563EB",
            },
        },
        indent=2,
        ensure_ascii=True,
    ) + "\n"


def _render_mcp_config(workspace_root: Path) -> str:
    """Render Codex MCP config for the local-checkout MVP."""
    return json.dumps(
        {
            "mcpServers": {
                SERVER_NAME: {
                    "command": sys.executable,
                    "args": [
                        "-m",
                        "examples.openstudio_ai.openstudio_mcp.server",
                        "--transport",
                        "stdio",
                        "--workspace-root",
                        str(workspace_root / ".openstudio_mcp_workspace"),
                    ],
                    "env": {
                        "PYTHONPATH": str(workspace_root.parents[1]),
                        "OPENSTUDIO_AI_ROOT": str(workspace_root),
                    },
                }
            }
        },
        indent=2,
        ensure_ascii=True,
    ) + "\n"


def _render_marketplace_json(plugin_name: str) -> str:
    """Render a repo-local Codex marketplace manifest."""
    return json.dumps(
        {
            "name": MARKETPLACE_NAME,
            "interface": {
                "displayName": "OpenStudio AI Local",
            },
            "plugins": [
                {
                    "name": plugin_name,
                    "source": {
                        "source": "local",
                        "path": f"./plugins/{plugin_name}",
                    },
                    "policy": {
                        "installation": "AVAILABLE",
                        "authentication": "ON_INSTALL",
                    },
                    "category": "Engineering",
                }
            ],
        },
        indent=2,
        ensure_ascii=True,
    ) + "\n"


def _render_install_doc(export_root: Path, marketplace_path: Path, plugin_name: str) -> str:
    """Render installation instructions for the exported Codex plugin."""
    return (
        "# Install OpenStudio AI In Codex\n\n"
        "This export is a local Codex marketplace containing the OpenStudio AI plugin.\n\n"
        "## 1. Validate The Plugin\n\n"
        "From the BEM-AI repository:\n\n"
        "```bash\n"
        f"{sys.executable} /Users/xuwe123/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py {export_root / 'plugins' / plugin_name}\n"
        "```\n\n"
        "## 2. Add The Local Marketplace\n\n"
        "Use this marketplace file with Codex:\n\n"
        "```bash\n"
        f"codex plugin marketplace add {export_root}\n"
        "```\n\n"
        "## 3. Install Or View The Plugin\n\n"
        "Open the Codex plugin UI and install `openstudio-ai` from `openstudio-ai-local`.\n\n"
        "## MVP Limitation\n\n"
        "This export references the local BEM-AI checkout for the MCP server. Keep the "
        "repository and Python environment available while testing.\n"
    )


def _render_plugin_readme(plan: HostLaunchPlan) -> str:
    """Render the README shipped with the Codex plugin."""
    skill_names = "\n".join(f"- `{_skill_dir_name(path)}`" for path in plan.skill_paths)
    return (
        "# OpenStudio AI\n\n"
        "OpenStudio AI is a Codex plugin package for building-energy modeling workflows "
        "using OpenStudio, MCP tools, reusable skills, and reviewed knowledge.\n\n"
        "## What It Includes\n\n"
        "- `.mcp.json`: registers the `openstudio_ai` MCP server.\n"
        "- `skills/`: separate runtime skills for model editing and HVAC workflows.\n"
        "- `knowledge/`: reviewed OpenStudio SDK recipes and context packs.\n"
        "- `instructions/`: harness, blackboard, learning, and promotion contracts.\n"
        "- `blackboard/schemas/`: workflow-state schema for long-running tasks.\n\n"
        "## Skills\n\n"
        f"{skill_names}\n\n"
        "## Runtime Note\n\n"
        "This MVP plugin references the local OpenStudio AI checkout for its MCP server. "
        "A later distributable package should vendor or install the MCP runtime.\n"
    )


def _render_connectors_doc(workspace_root: Path) -> str:
    """Render connector documentation for the Codex plugin package."""
    return (
        "# OpenStudio AI Connectors\n\n"
        "This plugin uses one local MCP server.\n\n"
        "| Connector | Type | Purpose |\n"
        "| --- | --- | --- |\n"
        "| `openstudio_ai` | local stdio MCP | OpenStudio model lifecycle, simulation, "
        "results, approved measures, and SDK documentation lookup |\n\n"
        "The MVP `.mcp.json` points to the local checkout:\n\n"
        f"- `{workspace_root}`\n"
    )


def _skill_dir_name(path: Path) -> str:
    """Convert repo skill filenames into plugin skill folder names."""
    return path.stem.replace("_", "-")


def _default_workspace_root() -> Path:
    """Return the OpenStudio AI example root from this adapter module."""
    return Path(__file__).resolve().parents[1]


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for Codex plugin export."""
    parser = argparse.ArgumentParser(description="Export the OpenStudio AI harness as a Codex plugin.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export = subparsers.add_parser("export-plugin", help="Export a Codex plugin and local marketplace.")
    export.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where the local marketplace and plugin folder should be created.",
    )
    export.add_argument(
        "--plugin-name",
        default=DEFAULT_PLUGIN_NAME,
        help="Plugin folder name and install name.",
    )
    export.add_argument(
        "--workspace-root",
        type=Path,
        default=_default_workspace_root(),
        help="OpenStudio AI harness root.",
    )
    export.add_argument("--dry-run", action="store_true", help="Preview package files without writing them.")
    export.add_argument("--force", action="store_true", help="Replace an existing plugin folder.")
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint for Codex adapter operations."""
    args = _parse_args()
    if args.command == "export-plugin":
        adapter = CodexAdapter(
            config=HostAdapterConfig(
                host_name="codex",
                workspace_root=args.workspace_root,
            )
        )
        result = adapter.export_plugin(
            args.output_dir,
            plugin_name=args.plugin_name,
            dry_run=args.dry_run,
            force=args.force,
        )
        mode = "Would export" if result.dry_run else "Exported"
        print(f"{mode} marketplace: {result.marketplace_path}")
        print(f"{mode} plugin: {result.plugin_dir}")
        for path in result.files:
            print(f"- {path}")
        return 0
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
