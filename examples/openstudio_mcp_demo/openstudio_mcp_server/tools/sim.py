from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from examples.openstudio_mcp_demo.openstudio_mcp_server.tools.schemas import (
    SimArtifactsArgs,
    SimRunArgs,
    SimStatusArgs,
    error_payload,
    validation_error_payload,
)


def register_sim_tools(mcp, service) -> None:
    @mcp.tool(name="sim_run", description="Start an OpenStudio simulation job.")
    async def sim_run(
        model_id: str,
        run_mode: str = "sizing",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            args = SimRunArgs(model_id=model_id, run_mode=run_mode, options=options or {})
            payload = service.sim_run(args)
            await service.schedule_simulation(
                job_id=payload["job_id"],
                model_id=model_id,
                options=args.options,
            )
            return payload
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except ValueError as exc:
            return error_payload("invalid_state", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=True)

    @mcp.tool(name="sim_status", description="Get simulation status.")
    async def sim_status(job_id: str) -> dict[str, Any]:
        try:
            args = SimStatusArgs(job_id=job_id)
            return service.sim_status(args)
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=True)

    @mcp.tool(name="sim_artifacts", description="Get simulation artifact IDs.")
    async def sim_artifacts(job_id: str) -> dict[str, Any]:
        try:
            args = SimArtifactsArgs(job_id=job_id)
            return service.sim_artifacts(args)
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except ValueError as exc:
            return error_payload("job_not_ready", str(exc), retryable=True)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=True)
