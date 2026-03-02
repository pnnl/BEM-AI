# OpenStudio MCP Demo

This example shows an `AgentFactory`-based AUTOMA-AI agent connected to a real MCP server that exposes a minimal OpenStudio modeling/simulation lifecycle.

## What is `openstudio_mcp`?

`openstudio_mcp` is a real MCP server (Anthropic `mcp`/`FastMCP`) that exposes OpenStudio workflows as MCP tools for AUTOMA-AI agents.

It provides:

- `model.*` tools for model lifecycle operations.
- `sim.*` tools for asynchronous OpenStudio simulation execution.
- `results.*` tools for SQL-backed post-processing and summarization.

## Architecture

The example has four layers:

1. Agent layer
- `examples/openstudio_mcp_demo/agent.py`
- Built with `AgentFactory`.
- Connects to MCP and orchestrates workflow/tool calls.

2. MCP server layer
- `examples/openstudio_mcp_demo/openstudio_mcp_server/server.py`
- Registers model/sim/results MCP tools.
- Uses standard MCP success/error envelope.

3. Runtime/state layer
- `runtime/workspace_manager.py`: per-job sandbox folders and quota checks.
- `runtime/job_manager.py`: `RUNNING/SUCCEEDED/FAILED` lifecycle.
- `runtime/artifact_store.py`: immutable artifact IDs and metadata.
- `runtime/measure_registry.py`: policy-based measure lookup and arg validation.

4. Governance/extension layer
- `policy/tool_allowlist.yaml`
- `policy/run_gates.yaml`
- `policy/measure_registry.yaml`
- `skills/hvac_sizing_assistant.md`

## Capabilities

### Model tools

- `model.load(model_uri)`
- `model.clone(model_id)`
- `model.list_measures()`
- `model.set_weather(model_id, epw_path)`
- `model.set_design_days(model_id, ddy_id | derive_from_epw=true)` (compatibility step)
- `model.apply_measure(model_id, measure_id, args)`
- `model.validate(model_id)`

### Simulation tools

- `sim.run(model_id, run_mode, options)` returns `job_id` immediately.
- `sim.status(job_id)` supports polling asynchronous simulation.
- `sim.artifacts(job_id)` returns result artifact IDs.

### Results tools

`results.query(sql_id, query_type, params)` supports:

- `annual_end_use_fuel`
- `design_day_end_use_fuel`
- `annual_eui`
- `sizing_summary`

`results.summarize(data, format)` returns readable summary text/tables.

## Setup

1. Copy `sample.env` to `.env`.
2. Update model and server settings as needed.
3. Set `OPENSTUDIO_PATH` to the local OpenStudio CLI executable path.

## Run

- Start agent server + MCP server:
  - `python3 examples/openstudio_mcp_demo/agent.py`
- Optional Streamlit UI:
  - `streamlit run examples/openstudio_mcp_demo/ui.py`
- Combined launcher:
  - `bash examples/openstudio_mcp_demo/run_all.sh`

## Troubleshooting

- If MCP tools are unavailable, confirm MCP server startup log in `examples/openstudio_mcp_demo/logs/server.log`.
- If chat responses stall, confirm the configured LLM endpoint/model is available.
- If `sim.run` fails, verify `OPENSTUDIO_PATH` points to a valid OpenStudio executable and ensure the model contains a valid `OS:WeatherFile` path (or pass one via `model.set_weather` / `sim.run` options with `epw_path`).
- Simulation runtime files are generated under `.openstudio_mcp_workspace/<job_id>/` (including `run/eplusout.sql`).
- If `model.apply_measure` fails, verify `policy/measure_registry.yaml` contains an allowed entry and the script exists under `measures/`.

## Results Query Types

`results.query` now reads real data from `eplusout.sql` and supports:

- `annual_end_use_fuel`: Annual end-use by fuel matrix from `AnnualBuildingUtilityPerformanceSummary -> End Uses`.
- `design_day_end_use_fuel`: Design-day energy by end-use/fuel from `ReportMeterDataDictionary` + `ReportMeterData`.
- `annual_eui`: Total site energy and EUI (kBtu/ft²) derived from SQL tabular outputs.
- `sizing_summary`: Consolidated payload including all three query outputs above.

## Measures

- Measure registry policy: `examples/openstudio_mcp_demo/policy/measure_registry.yaml`
- Built-in measure: `add_daylighting` (`examples/openstudio_mcp_demo/measures/add_daylighting.py`)
- Discover measures at runtime with `model.list_measures`.
- `model.apply_measure` resolves `measure_id` via policy, validates args/defaults, executes with:
  - `openstudio execute_python_script <entrypoint>`
  - environment variables `OSM_INPUT_PATH`, `OSM_OUTPUT_PATH`, `MEASURE_ARGS_JSON`
- On success, a new model artifact/state is created and returned as `model_id`.

### Measure interface contract

`model.apply_measure` is policy-driven:

1. Resolve `measure_id` from `measure_registry.yaml`.
2. Validate/default `args` using registered schema.
3. Execute script using:
   - `openstudio execute_python_script <entrypoint>`
4. Pass runtime env vars:
   - `OSM_INPUT_PATH`
   - `OSM_OUTPUT_PATH`
   - `MEASURE_ARGS_JSON`
5. Register a new immutable model artifact and return its `model_id`.

## File map

- `examples/openstudio_mcp_demo/agent.py`: AgentFactory-based bootstrap.
- `examples/openstudio_mcp_demo/architecture_diagram.md`: Sponsor-friendly architecture/workflow diagrams.
- `examples/openstudio_mcp_demo/ADVANCED_USER_GUIDE.md`: Advanced extension guide for measures, policies, and skills.
- `examples/openstudio_mcp_demo/openstudio_mcp_server/server.py`: MCP server entrypoint.
- `examples/openstudio_mcp_demo/openstudio_mcp_server/tools/`: model/sim/results tools.
- `examples/openstudio_mcp_demo/openstudio_mcp_server/runtime/`: workspace, artifact, job managers.
- `examples/openstudio_mcp_demo/skills/hvac_sizing_assistant.md`: skill prompt contract.
- `examples/openstudio_mcp_demo/policy/*.yaml`: allowlist and runtime gates.
