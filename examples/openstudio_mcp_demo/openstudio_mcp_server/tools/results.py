from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from examples.openstudio_mcp_demo.openstudio_mcp_server.tools.schemas import (
    ResultsQueryArgs,
    ResultsSummarizeArgs,
    error_payload,
    validation_error_payload,
)


def register_results_tools(mcp, service) -> None:
    @mcp.tool(
        name="results.query",
        description=(
            "Query simulation result data by SQL artifact. "
            "query_type must be one of: annual_end_use_fuel, design_day_end_use_fuel, "
            "annual_eui, sizing_summary, sql."
        ),
    )
    async def results_query(
        sql_id: str,
        query_type: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            args = ResultsQueryArgs(sql_id=sql_id, query_type=query_type, params=params or {})
            return service.results_query(args)
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(name="results.summarize", description="Summarize queried results into text/tables.")
    async def results_summarize(data: Any, format: str = "json") -> dict[str, Any]:
        try:
            args = ResultsSummarizeArgs(data=data, format=format)
            return service.results_summarize(args)
        except ValidationError as exc:
            return validation_error_payload(exc)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)
