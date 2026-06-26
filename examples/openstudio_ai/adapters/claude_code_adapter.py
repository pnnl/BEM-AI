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


GENERATED_START = "<!-- BEGIN OPENSTUDIO_AI_HARNESS -->"
GENERATED_END = "<!-- END OPENSTUDIO_AI_HARNESS -->"
SERVER_NAME = "openstudio_ai"
DEFAULT_PLUGIN_NAME = "openstudio-ai"
MARKETPLACE_NAME = "openstudio-ai-local"


@dataclass(frozen=True)
class InstallAction:
    """A single file write planned by the project-level Claude install path."""

    path: Path
    action: str
    content: str


@dataclass(frozen=True)
class InstallResult:
    """Result for project-level installation into an existing Claude Code workspace."""

    dry_run: bool
    target_dir: Path
    actions: list[InstallAction]


@dataclass(frozen=True)
class PluginExportResult:
    """Result for exporting a plugin-style package for Claude hosts."""

    dry_run: bool
    marketplace_dir: Path
    plugin_dir: Path
    files: list[Path]


class ClaudeCodeAdapter(OpenStudioAiHostAdapter):
    """Adapter contract for installing OpenStudio AI into Claude Code-style hosts."""

    def build_launch_plan(self) -> HostLaunchPlan:
        """Resolve the host-facing assets from the OpenStudio AI harness registry."""
        assets = discover_harness_assets(self.config.workspace_root)
        return HostLaunchPlan(
            host_name="claude_code",
            system_prompt_files=assets.prompt_contracts,
            skill_paths=assets.skill_files,
            mcp_entrypoint=assets.mcp_entrypoint,
            blackboard_schema=assets.blackboard_schema,
            learning_event_log=assets.learning_event_log,
            notes=["Map harness files into the host's project instructions and MCP config."],
        )

    def build_install_actions(self, target_dir: Path, *, force: bool = False) -> list[InstallAction]:
        """Plan project-local Claude Code files without writing them.

        This is the development/debug path. The distributable path is
        `export_plugin`, which keeps skills and knowledge in separate plugin
        package folders instead of flattening them into CLAUDE.md.
        """
        target_dir = target_dir.resolve()
        plan = self.build_launch_plan()
        actions = [
            InstallAction(
                path=target_dir / ".mcp.json",
                action="write_mcp_config",
                content=_render_mcp_config(
                    existing_path=target_dir / ".mcp.json",
                    plan=plan,
                    workspace_root=self.config.workspace_root.resolve(),
                ),
            ),
            InstallAction(
                path=target_dir / ".claude" / "CLAUDE.md",
                action="write_project_instructions",
                content=_render_claude_instructions(
                    existing_path=target_dir / ".claude" / "CLAUDE.md",
                    plan=plan,
                    workspace_root=self.config.workspace_root.resolve(),
                    force=force,
                ),
            ),
        ]
        return actions

    def install(self, target_dir: Path, *, dry_run: bool = True, force: bool = False) -> InstallResult:
        """Write or preview project-local Claude Code configuration files."""
        actions = self.build_install_actions(target_dir, force=force)
        if not dry_run:
            for action in actions:
                action.path.parent.mkdir(parents=True, exist_ok=True)
                action.path.write_text(action.content, encoding="utf-8")
        return InstallResult(dry_run=dry_run, target_dir=target_dir.resolve(), actions=actions)

    def export_plugin(
        self,
        output_dir: Path,
        *,
        plugin_name: str = DEFAULT_PLUGIN_NAME,
        dry_run: bool = True,
        force: bool = False,
    ) -> PluginExportResult:
        """Export a Claude plugin-style package with separate skills and knowledge.

        The exported package intentionally mirrors Anthropic's knowledge-work
        plugin layout: metadata, MCP config, commands, skills, knowledge, and
        instructions remain distinct files/folders.
        """
        workspace_root = self.config.workspace_root.resolve()
        marketplace_dir = output_dir.resolve()
        plugin_dir = (marketplace_dir / plugin_name).resolve()
        plan = self.build_launch_plan()
        files = _planned_export_files(marketplace_dir, plugin_dir, plan, workspace_root)

        if dry_run:
            return PluginExportResult(
                dry_run=True,
                marketplace_dir=marketplace_dir,
                plugin_dir=plugin_dir,
                files=files,
            )

        if plugin_dir.exists():
            if not force:
                raise FileExistsError(f"{plugin_dir} already exists. Use --force to replace it.")
            shutil.rmtree(plugin_dir)

        (marketplace_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (marketplace_dir / ".claude-plugin" / "marketplace.json").write_text(
            _render_marketplace_json(plugin_name),
            encoding="utf-8",
        )
        (marketplace_dir / "INSTALL.md").write_text(
            _render_install_doc(marketplace_dir, plugin_name),
            encoding="utf-8",
        )
        _write_plugin_package(plugin_dir, plan, workspace_root)
        return PluginExportResult(
            dry_run=False,
            marketplace_dir=marketplace_dir,
            plugin_dir=plugin_dir,
            files=files,
        )


def _render_mcp_config(existing_path: Path, plan: HostLaunchPlan, workspace_root: Path) -> str:
    """Render project-level `.mcp.json` while preserving unrelated servers."""
    existing: dict[str, object] = {}
    if existing_path.exists():
        existing = json.loads(existing_path.read_text(encoding="utf-8"))
    mcp_servers = dict(existing.get("mcpServers", {})) if isinstance(existing.get("mcpServers"), dict) else {}
    # Current local-export behavior: use this Python environment and source
    # checkout. A packaged release should replace this with an installed command
    # or vendored runtime.
    mcp_servers[SERVER_NAME] = {
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
    existing["mcpServers"] = mcp_servers
    return json.dumps(existing, indent=2, ensure_ascii=True) + "\n"


def _render_plugin_mcp_config(workspace_root: Path) -> str:
    """Render plugin `.mcp.json` for a local-checkout package."""
    # This is intentionally the same stdio MCP entrypoint as project install.
    # The deployment roadmap replaces this local checkout path with a packaged
    # runtime entrypoint.
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


def _render_claude_instructions(
    existing_path: Path,
    plan: HostLaunchPlan,
    workspace_root: Path,
    *,
    force: bool,
) -> str:
    """Render or update a project-level CLAUDE.md block.

    Generated markers let the adapter refresh its own block without rewriting
    hand-authored project instructions. Unmanaged files require `--force`.
    """
    generated = _generated_instruction_block(plan, workspace_root)
    if not existing_path.exists():
        return generated

    existing = existing_path.read_text(encoding="utf-8")
    if GENERATED_START in existing and GENERATED_END in existing:
        before, rest = existing.split(GENERATED_START, 1)
        _, after = rest.split(GENERATED_END, 1)
        return before.rstrip() + "\n\n" + generated + "\n" + after.lstrip()

    if not force:
        raise FileExistsError(
            f"{existing_path} already exists and is not managed by OpenStudio AI. "
            "Use --force to append the generated OpenStudio AI block."
        )

    return existing.rstrip() + "\n\n" + generated


def _generated_instruction_block(plan: HostLaunchPlan, workspace_root: Path) -> str:
    """Render the minimal project-install instruction block.

    This block is deliberately only a pointer map. It is not the plugin export
    format and should not contain full skill or knowledge-base content.
    """
    prompt_lines = "\n".join(f"- `{path}`" for path in plan.system_prompt_files)
    skill_lines = "\n".join(f"- `{path}`" for path in plan.skill_paths)
    return (
        f"{GENERATED_START}\n"
        "# OpenStudio AI Harness\n\n"
        "Use OpenStudio AI for OpenStudio model inspection, model editing, simulation, "
        "result retrieval, SDK lookup, and workflow skill guidance.\n\n"
        "## Runtime Boundaries\n\n"
        "- Use the `openstudio_ai` MCP server for model lifecycle, simulation, results, "
        "approved measures, and SDK documentation lookup.\n"
        "- Use the listed OpenStudio AI skill files as workflow guidance.\n"
        "- Treat the blackboard schema as the source of truth for long-running workflow state.\n"
        "- Runtime learning may create candidate assets only; trusted assets require review and eval validation.\n\n"
        "## Harness Paths\n\n"
        f"- Root: `{workspace_root}`\n"
        f"- MCP entrypoint: `{plan.mcp_entrypoint}`\n"
        f"- Blackboard schema: `{plan.blackboard_schema}`\n"
        f"- Learning event log: `{plan.learning_event_log}`\n\n"
        "## Prompt Contracts\n\n"
        f"{prompt_lines}\n\n"
        "## Runtime Skills\n\n"
        f"{skill_lines}\n"
        f"{GENERATED_END}\n"
    )


def _planned_export_files(
    marketplace_dir: Path,
    plugin_dir: Path,
    plan: HostLaunchPlan,
    workspace_root: Path,
) -> list[Path]:
    """Return the marketplace and plugin files that `export_plugin` would create.

    Dry-run uses this list for review, while tests use it to keep the package
    contract stable.
    """
    files = [
        marketplace_dir / ".claude-plugin" / "marketplace.json",
        marketplace_dir / "INSTALL.md",
        plugin_dir / ".claude-plugin" / "plugin.json",
        plugin_dir / ".mcp.json",
        plugin_dir / "README.md",
        plugin_dir / "CONNECTORS.md",
        plugin_dir / "commands" / "add-vav-reheat.md",
        plugin_dir / "commands" / "simulate.md",
        plugin_dir / "commands" / "query-results.md",
        plugin_dir / "commands" / "propose-measure.md",
        plugin_dir / "blackboard" / "schemas" / plan.blackboard_schema.name,
        plugin_dir / "learning" / "README.md",
        plugin_dir / "learning" / "candidates" / ".gitkeep",
    ]
    files.extend(plugin_dir / "instructions" / path.name for path in plan.system_prompt_files)
    files.extend(plugin_dir / "skills" / _skill_dir_name(path) / "SKILL.md" for path in plan.skill_paths)
    files.extend(
        plugin_dir / "learning" / "schemas" / path.name
        for path in sorted((workspace_root / "learning" / "harness_pipeline" / "schemas").glob("*.json"))
    )
    for root in [workspace_root / "knowledge"]:
        if root.exists():
            files.extend(plugin_dir / "knowledge" / path.relative_to(root) for path in root.rglob("*") if path.is_file())
    return sorted(files)


def _render_marketplace_json(plugin_name: str) -> str:
    """Render a local marketplace manifest that points at the exported plugin."""
    return json.dumps(
        {
            "$schema": "https://json.schemastore.org/claude-code-marketplace.json",
            "name": MARKETPLACE_NAME,
            "version": "0.1.0",
            "description": "Local marketplace for the OpenStudio AI Claude plugin.",
            "owner": {
                "name": "OpenStudio AI",
            },
            "plugins": [
                {
                    "name": plugin_name,
                    "description": (
                        "OpenStudio AI harness for OpenStudio model editing, simulation, "
                        "results, SDK lookup, and reusable workflow skills."
                    ),
                    "version": "0.1.0",
                    "source": f"./{plugin_name}",
                    "category": "engineering",
                }
            ],
        },
        indent=2,
        ensure_ascii=True,
    ) + "\n"


def _render_install_doc(marketplace_dir: Path, plugin_name: str) -> str:
    """Render install instructions for using the exported package in Claude Code."""
    return (
        "# Install OpenStudio AI In Claude Code\n\n"
        "This export is a local Claude Code marketplace containing the OpenStudio AI plugin.\n\n"
        "## 1. Validate The Export\n\n"
        "From the BEM-AI repository:\n\n"
        "```bash\n"
        f"claude plugin validate {marketplace_dir}\n"
        "```\n\n"
        "## 2. Add The Local Marketplace\n\n"
        "Open Claude Code in the target project and run:\n\n"
        "```text\n"
        f"/plugin marketplace add {marketplace_dir}\n"
        "```\n\n"
        "## 3. Install The Plugin\n\n"
        "Still inside Claude Code, run:\n\n"
        "```text\n"
        f"/plugin install {plugin_name}@{MARKETPLACE_NAME}\n"
        "```\n\n"
        "If Claude Code asks for scope, choose local or project scope for testing.\n\n"
        "## 4. Reload Plugins\n\n"
        "```text\n"
        "/reload-plugins\n"
        "```\n\n"
        "## 5. Try The Plugin\n\n"
        "Use one of the namespaced commands:\n\n"
        "```text\n"
        f"/{plugin_name}:add-vav-reheat\n"
        f"/{plugin_name}:simulate\n"
        f"/{plugin_name}:query-results\n"
        "```\n\n"
        "The plugin also contributes OpenStudio AI skills and an `openstudio_ai` MCP server.\n\n"
        "## Current Packaging Limit\n\n"
        "This export references the local BEM-AI checkout for the MCP server. Keep the "
        "repository and Python environment available until a packaged runtime "
        "entrypoint is available.\n"
    )


def _write_plugin_package(plugin_dir: Path, plan: HostLaunchPlan, workspace_root: Path) -> None:
    """Materialize the plugin package on disk."""
    (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "commands").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "skills").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "instructions").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "blackboard" / "schemas").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "learning" / "schemas").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "learning" / "candidates").mkdir(parents=True, exist_ok=True)

    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "openstudio-ai",
                "version": "0.1.0",
                "description": (
                    "OpenStudio AI harness for model editing, simulation, results, "
                    "SDK lookup, and reusable building-energy workflow skills."
                ),
                "author": {"name": "OpenStudio AI"},
                "keywords": ["openstudio", "building-energy-modeling", "mcp", "simulation"],
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (plugin_dir / ".mcp.json").write_text(_render_plugin_mcp_config(workspace_root), encoding="utf-8")
    (plugin_dir / "README.md").write_text(_render_plugin_readme(plan), encoding="utf-8")
    (plugin_dir / "CONNECTORS.md").write_text(_render_connectors_doc(workspace_root), encoding="utf-8")

    for command_name, content in _command_docs().items():
        (plugin_dir / "commands" / command_name).write_text(content, encoding="utf-8")

    for prompt in plan.system_prompt_files:
        shutil.copy2(prompt, plugin_dir / "instructions" / prompt.name)

    for skill in plan.skill_paths:
        target_dir = plugin_dir / "skills" / _skill_dir_name(skill)
        target_dir.mkdir(parents=True, exist_ok=True)
        # Claude plugin skills use folder-per-skill layout with SKILL.md.
        shutil.copy2(skill, target_dir / "SKILL.md")

    shutil.copy2(plan.blackboard_schema, plugin_dir / "blackboard" / "schemas" / plan.blackboard_schema.name)
    shutil.copy2(
        workspace_root / "learning" / "harness_pipeline" / "runtime_learning.md",
        plugin_dir / "learning" / "README.md",
    )
    (plugin_dir / "learning" / "candidates" / ".gitkeep").write_text("", encoding="utf-8")
    for schema in sorted((workspace_root / "learning" / "harness_pipeline" / "schemas").glob("*.json")):
        shutil.copy2(schema, plugin_dir / "learning" / "schemas" / schema.name)

    knowledge_root = workspace_root / "knowledge"
    if knowledge_root.exists():
        shutil.copytree(knowledge_root, plugin_dir / "knowledge")


def _skill_dir_name(path: Path) -> str:
    """Convert repo skill filenames into plugin skill folder names."""
    return path.stem.replace("_", "-")


def _render_plugin_readme(plan: HostLaunchPlan) -> str:
    """Render the README shipped with the exported plugin."""
    skill_names = "\n".join(f"- `{_skill_dir_name(path)}`" for path in plan.skill_paths)
    return (
        "# OpenStudio AI\n\n"
        "OpenStudio AI is a Claude plugin package for building-energy modeling "
        "workflows using OpenStudio, MCP tools, reusable skills, and a reviewed "
        "knowledge base.\n\n"
        "## What It Includes\n\n"
        "- `.mcp.json`: registers the `openstudio_ai` MCP server.\n"
        "- `skills/`: separate runtime skills for model editing and HVAC workflows.\n"
        "- `commands/`: user-facing workflow entry points.\n"
        "- `knowledge/`: reviewed OpenStudio SDK recipes and context packs.\n"
        "- `instructions/`: harness, blackboard, learning, and promotion contracts.\n"
        "- `blackboard/schemas/`: workflow-state schema for long-running tasks.\n\n"
        "## Commands\n\n"
        "- `/openstudio-ai:add-vav-reheat`: plan and execute a VAV reheat workflow.\n"
        "- `/openstudio-ai:simulate`: run or prepare an OpenStudio simulation workflow.\n"
        "- `/openstudio-ai:query-results`: retrieve SQL-backed simulation results.\n\n"
        "## Skills\n\n"
        f"{skill_names}\n\n"
        "## Runtime Note\n\n"
        "This plugin currently references the local OpenStudio AI checkout for its "
        "MCP server. A deployment package should vendor or install the MCP runtime "
        "instead of relying on a source checkout.\n"
    )


def _render_connectors_doc(workspace_root: Path) -> str:
    """Render connector documentation for the plugin package."""
    return (
        "# OpenStudio AI Connectors\n\n"
        "This plugin uses one local MCP server.\n\n"
        "| Connector | Type | Purpose |\n"
        "| --- | --- | --- |\n"
        "| `openstudio_ai` | local stdio MCP | OpenStudio model lifecycle, simulation, "
        "results, approved measures, and SDK documentation lookup |\n\n"
        "The current `.mcp.json` points to the local checkout:\n\n"
        f"- `{workspace_root}`\n\n"
        "OpenStudio and EnergyPlus availability depends on the local environment.\n"
    )


def _command_docs() -> dict[str, str]:
    """Return command files for common OpenStudio workflows."""
    return {
        "add-vav-reheat.md": _command_markdown(
            name="add-vav-reheat",
            description="Plan and execute a phased OpenStudio VAV reheat workflow.",
            body=(
            "# Add VAV Reheat\n\n"
            "Use the OpenStudio AI VAV reheat parent workflow skill. Maintain workflow "
            "state through the blackboard contract, load only the child skill needed "
            "for the current phase, and use MCP tools for deterministic model lifecycle "
            "operations when appropriate.\n"
            ),
        ),
        "simulate.md": _command_markdown(
            name="simulate",
            description="Run, poll, and collect artifacts from an OpenStudio simulation.",
            body=(
            "# Simulate\n\n"
            "Use the `openstudio_ai` MCP simulation tools to run, poll, and collect "
            "artifacts from OpenStudio simulations. Do not run simulations through "
            "ad hoc shell commands when MCP tools are available.\n"
            ),
        ),
        "query-results.md": _command_markdown(
            name="query-results",
            description="Query SQL-backed OpenStudio simulation results through MCP tools.",
            body=(
            "# Query Results\n\n"
            "Use the `openstudio_ai` MCP result tools for SQL-backed annual, design-day, "
            "and summary result retrieval. Attribute assumptions and missing outputs "
            "in the final answer.\n"
            ),
        ),
        "propose-measure.md": _command_markdown(
            name="propose-measure",
            description="Draft a candidate OpenStudio measure from a repeated script or workflow.",
            body=(
                "# Propose Measure\n\n"
                "Summarize the repeated OpenStudio script or workflow as a candidate measure. "
                "Write candidate JSON to `learning/candidates/` using "
                "`learning/schemas/candidate_measure.schema.json`. Do not edit trusted "
                "`knowledge/`, `skills/`, or approved measures directly. State that review "
                "and eval validation are required before promotion.\n"
            ),
        ),
    }


def _command_markdown(*, name: str, description: str, body: str) -> str:
    """Render a Claude Code command file with required YAML frontmatter."""
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"{body}"
    )


def _default_workspace_root() -> Path:
    """Return the OpenStudio AI example root from this adapter module."""
    return Path(__file__).resolve().parents[1]


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for project install and plugin export."""
    parser = argparse.ArgumentParser(description="Install the OpenStudio AI harness into Claude Code.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser("install", help="Create or preview Claude Code project config.")
    install.add_argument(
        "--target-dir",
        type=Path,
        default=Path.cwd(),
        help="Project directory where .mcp.json and .claude/CLAUDE.md should be written.",
    )
    install.add_argument(
        "--workspace-root",
        type=Path,
        default=_default_workspace_root(),
        help="OpenStudio AI harness root.",
    )
    install.add_argument("--dry-run", action="store_true", help="Preview files without writing them.")
    install.add_argument("--force", action="store_true", help="Append to an existing unmanaged CLAUDE.md.")

    export = subparsers.add_parser("export-plugin", help="Export a Claude plugin-style package.")
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
    """CLI entrypoint for Claude Code adapter operations."""
    args = _parse_args()
    if args.command == "install":
        adapter = ClaudeCodeAdapter(
            config=HostAdapterConfig(
                host_name="claude_code",
                workspace_root=args.workspace_root,
            )
        )
        result = adapter.install(args.target_dir, dry_run=args.dry_run, force=args.force)
        mode = "Would write" if result.dry_run else "Wrote"
        for action in result.actions:
            print(f"{mode} {action.path} ({action.action})")
            if result.dry_run:
                print(action.content)
        return 0
    if args.command == "export-plugin":
        adapter = ClaudeCodeAdapter(
            config=HostAdapterConfig(
                host_name="claude_code",
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
        print(f"{mode} marketplace: {result.marketplace_dir}")
        print(f"{mode} plugin: {result.plugin_dir}")
        for path in result.files:
            print(f"- {path}")
        return 0
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
