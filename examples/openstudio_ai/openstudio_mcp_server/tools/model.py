from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from examples.openstudio_ai.openstudio_mcp_server.tools.schemas import (
    ModelApplyMeasureArgs,
    ModelCloneArgs,
    ModelLoadArgs,
    ModelSetDesignDaysArgs,
    ModelSetWeatherArgs,
    error_payload,
    success_payload,
    validation_error_payload,
)


def register_model_tools(mcp, service) -> None:
    @mcp.tool(name="model_load", description="Load an OpenStudio model artifact from URI.")
    async def model_load(model_uri: str) -> dict[str, Any]:
        try:
            args = ModelLoadArgs(model_uri=model_uri)
            return service.model_load(args)
        except ValidationError as exc:
            return validation_error_payload(exc)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(name="model_clone", description="Clone an existing model artifact and return new model_id.")
    async def model_clone(model_id: str) -> dict[str, Any]:
        try:
            args = ModelCloneArgs(model_id=model_id)
            return service.model_clone(args)
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(name="model_set_weather", description="Attach local weather file path to model.")
    async def model_set_weather(model_id: str, epw_path: str) -> dict[str, Any]:
        try:
            args = ModelSetWeatherArgs(model_id=model_id, epw_path=epw_path)
            return service.model_set_weather(args)
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(name="model_set_design_days", description="Configure design days for model.")
    async def model_set_design_days(
        model_id: str,
        ddy_id: str | None = None,
        derive_from_epw: bool = False,
    ) -> dict[str, Any]:
        try:
            args = ModelSetDesignDaysArgs(
                model_id=model_id,
                ddy_id=ddy_id,
                derive_from_epw=derive_from_epw,
            )
            return service.model_set_design_days(args)
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except ValueError as exc:
            return error_payload("invalid_state", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(
        name="model_list_measures",
        description="List registered/allowed measures and their argument schemas.",
    )
    async def model_list_measures() -> dict[str, Any]:
        try:
            return service.model_list_measures()
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(
        name="model_apply_measure",
        description="Apply a registered measure to a model. Call model_list_measures first to discover measure_id and args schema.",
    )
    async def model_apply_measure(
        model_id: str,
        measure_id: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            parsed = ModelApplyMeasureArgs(
                model_id=model_id,
                measure_id=measure_id,
                args=args or {},
            )
            return service.model_apply_measure(parsed)
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except PermissionError as exc:
            return error_payload("forbidden", str(exc), retryable=False)
        except FileNotFoundError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except ValueError as exc:
            return error_payload("invalid_state", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(name="model_validate", description="Validate model for simulation readiness.")
    async def model_validate(model_id: str) -> dict[str, Any]:
        try:
            args = ModelCloneArgs(model_id=model_id)
            return service.model_validate(args)
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)
