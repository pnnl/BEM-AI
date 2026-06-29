from __future__ import annotations

from typing import Any

from examples.openstudio_ai.openstudio_mcp.tools.schemas import error_payload


def register_runtime_tools(mcp, service) -> None:
    @mcp.tool(
        name="runtime_storage_usage",
        description="Report local OpenStudio AI MCP runtime workspace usage and registry state.",
    )
    async def runtime_storage_usage() -> dict[str, Any]:
        try:
            return service.runtime_storage_usage()
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(
        name="runtime_prune_preview",
        description=(
            "Preview safe local workspace prune candidates. This does not delete files. "
            "Active models, running jobs, and pinned workspaces are protected."
        ),
    )
    async def runtime_prune_preview(
        include_measure_workspaces: bool = True,
        include_failed_simulations: bool = True,
        include_successful_simulations: bool = False,
    ) -> dict[str, Any]:
        try:
            return service.runtime_prune_preview(
                include_measure_workspaces=include_measure_workspaces,
                include_failed_simulations=include_failed_simulations,
                include_successful_simulations=include_successful_simulations,
            )
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(
        name="runtime_prune",
        description=(
            "Delete safe local workspace prune candidates. By default this prunes "
            "unprotected measure workspaces and failed simulation workspaces only."
        ),
    )
    async def runtime_prune(
        workspace_ids: list[str] | None = None,
        include_measure_workspaces: bool = True,
        include_failed_simulations: bool = True,
        include_successful_simulations: bool = False,
    ) -> dict[str, Any]:
        try:
            return service.runtime_prune(
                workspace_ids=workspace_ids,
                include_measure_workspaces=include_measure_workspaces,
                include_failed_simulations=include_failed_simulations,
                include_successful_simulations=include_successful_simulations,
            )
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)
