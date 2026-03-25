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

- `model.load`
- `model.clone`
- `model.list_measures`
- `model.set_weather`
- `model.set_design_days`
- `model.apply_measure`
- `model.validate`
- `sim.run`
- `sim.status`
- `sim.artifacts`
- `results.query`
- `results.summarize`

## Steps

A. Load the model via `model.load`.
B. Clone the loaded model via `model.clone`.
C. Apply HVAC template measure (`model.apply_measure`).
D. Validate readiness (`model.validate`).
E. Launch sizing simulation (`sim.run`) and poll status (`sim.status`).
F. Fetch artifacts (`sim.artifacts`).
G. Query sizing outputs (`results.query` with `query_type=sizing_summary`).
H. Summarize outputs (`results.summarize`) and return assumptions + artifact IDs.

## Error Handling

- Return standard MCP error envelope on any failed tool call.
- Stop workflow on first hard failure.
- Treat `sim.artifacts` before `SUCCEEDED` as retryable.

## Constraints & Assumptions

- Enforce tool allowlist prefixes: `model.*`, `sim.*`, `results.*`.
- Enforce run gates: `max_runtime_minutes`, `max_variants`.
- Current implementation requires a functioning OpenStudio runtime, model path, and weather file; `sim.run` and `results.query` will fail if these are unavailable (no stubbed behavior).

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
