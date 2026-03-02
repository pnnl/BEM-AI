from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError


class ToolError(BaseModel):
    type: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


class ModelLoadArgs(BaseModel):
    model_uri: str = Field(min_length=1)


class ModelCloneArgs(BaseModel):
    model_id: str = Field(min_length=1)


class ModelSetWeatherArgs(BaseModel):
    model_id: str = Field(min_length=1)
    epw_path: str = Field(
        min_length=1,
        description="Local EPW file path (absolute, relative, or file:// URI).",
    )


class ModelSetDesignDaysArgs(BaseModel):
    model_id: str = Field(min_length=1)
    ddy_id: str | None = None
    derive_from_epw: bool = False


class ModelApplyMeasureArgs(BaseModel):
    model_id: str = Field(min_length=1)
    measure_id: str = Field(
        min_length=1,
        description="Registered measure id from model.list_measures.",
    )
    args: dict[str, Any] = Field(
        default_factory=dict,
        description="Measure arguments; see args_schema from model.list_measures.",
    )


class SimRunArgs(BaseModel):
    model_id: str = Field(min_length=1)
    run_mode: str = Field(default="sizing")
    options: dict[str, Any] = Field(default_factory=dict)


class SimStatusArgs(BaseModel):
    job_id: str = Field(min_length=1)


class SimArtifactsArgs(BaseModel):
    job_id: str = Field(min_length=1)


class ResultsQueryArgs(BaseModel):
    sql_id: str = Field(min_length=1)
    query_type: Literal[
        "annual_end_use_fuel",
        "design_day_end_use_fuel",
        "annual_eui",
        "sizing_summary",
    ] = Field(
        description=(
            "Supported query types: annual_end_use_fuel, design_day_end_use_fuel, "
            "annual_eui, sizing_summary."
        )
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional query params (currently unused for built-in query types).",
    )


class ResultsSummarizeArgs(BaseModel):
    data: Any
    format: Literal["json", "markdown", "text"] = "json"


def success_payload(**data: Any) -> dict[str, Any]:
    return {"ok": True, **data}


def error_payload(
    err_type: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    return {
        "ok": False,
        "error": ToolError(
            type=err_type,
            message=message,
            details=details or {},
            retryable=retryable,
        ).model_dump(),
    }


def validation_error_payload(exc: ValidationError) -> dict[str, Any]:
    return error_payload(
        "validation_error",
        "Invalid tool arguments.",
        details={"errors": exc.errors()},
        retryable=False,
    )
