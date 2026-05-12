---
name: hvac_sizing_assistant
description: Run a sizing workflow through OpenStudio MCP and return structured sizing + assumptions + artifact IDs.
version: 0.1.0
output_format: json
---

## Objective

Run a constrained HVAC sizing workflow through OpenStudio MCP tools and return structured outputs, assumptions, and artifact IDs.

## Inputs

- `model_uri` (required)
- `epw_path` (optional local EPW path; defaults allowed via model metadata)
- `ddy_id` (optional)
- `derive_from_epw` (optional, default true)
- `hvac_template_measure` (optional)
- `measure_args` (optional object)

## Outputs

- Workflow status (`ok` or `error`)
- Model/job identifiers
- Validation issues
- Simulation artifact IDs (`osm_id`, `sql_id`, `logs_id`, `report_id`)
- Sizing query data and summary text/tables

## Allowed Tools

- `model_load`
- `model_clone`
- `model_list_measures`
- `model_set_weather`
- `model_set_design_days`
- `model_apply_measure`
- `model_validate`
- `sim_run`
- `sim_status`
- `sim_artifacts`
- `results_query`
- `results_summarize`

## Steps

A. Load the model via `model_load`.
B. Clone the loaded model via `model_clone`.
C. Apply HVAC template measure (`model_apply_measure`).
D. Validate readiness (`model_validate`).
E. Launch sizing simulation (`sim_run`) and poll status (`sim_status`).
F. Fetch artifacts (`sim_artifacts`).
G. Query sizing outputs (`results_query` with `query_type=sizing_summary`).
H. Summarize outputs (`results_summarize`) and return assumptions + artifact IDs.

## Error Handling

- Return standard MCP error envelope on any failed tool call.
- Stop workflow on first hard failure.
- Treat `sim_artifacts` before `SUCCEEDED` as retryable.

## Constraints & Assumptions

- Enforce tool allowlist prefixes: `model_*`, `sim_*`, `results_*`.
- Enforce run gates: `max_runtime_minutes`, `max_variants`.
- Current implementation requires a functioning OpenStudio runtime, model path, and weather file; `sim_run` and `results_query` will fail if these are unavailable (no stubbed behavior).

## Example invocation

```json
{
  "model_uri": "file:///tmp/demo.osm",
  "epw_path": "/absolute/path/to/weather.epw",
  "derive_from_epw": true,
  "hvac_template_measure": "hvac_template",
  "measure_args": {"system_type": "VAV"}
}
```
