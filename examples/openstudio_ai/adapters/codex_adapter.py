from __future__ import annotations

from examples.openstudio_ai.adapters.base import OpenStudioAiHostAdapter
from examples.openstudio_ai.adapters.contracts import HostLaunchPlan
from examples.openstudio_ai.harness.registry import discover_harness_assets


class CodexAdapter(OpenStudioAiHostAdapter):
    """Adapter contract for installing OpenStudio AI into Codex-style hosts."""

    def build_launch_plan(self) -> HostLaunchPlan:
        assets = discover_harness_assets(self.config.workspace_root)
        return HostLaunchPlan(
            host_name="codex",
            system_prompt_files=assets.prompt_contracts,
            skill_paths=assets.skill_files,
            mcp_entrypoint=assets.mcp_entrypoint,
            blackboard_schema=assets.blackboard_schema,
            learning_event_log=assets.learning_event_log,
            notes=["Load skills as file-backed prompt skills; connect MCP over configured transport."],
        )

