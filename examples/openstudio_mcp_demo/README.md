# OpenStudio MCP Demo

This example shows an `AgentFactory`-based AUTOMA-AI agent connected to a real MCP server that exposes a minimal OpenStudio modeling/simulation lifecycle.

## What this demonstrates

- Real MCP server using Anthropic `mcp` (`FastMCP`) under `openstudio_mcp_server/`.
- `AgentFactory` agent wiring to MCP tools via `mcp_configs`.
- Minimal sizing workflow instructions and policy constraints loaded from local skill/policy files.
- Policy-driven measure execution via `model.apply_measure` with user-extensible Python measures.

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

## File map

- `examples/openstudio_mcp_demo/agent.py`: AgentFactory-based bootstrap.
- `examples/openstudio_mcp_demo/architecture_diagram.md`: Sponsor-friendly architecture/workflow diagrams.
- `examples/openstudio_mcp_demo/ADVANCED_USER_GUIDE.md`: Advanced extension guide for measures, policies, and skills.
- `examples/openstudio_mcp_demo/openstudio_mcp_server/server.py`: MCP server entrypoint.
- `examples/openstudio_mcp_demo/openstudio_mcp_server/tools/`: model/sim/results tools.
- `examples/openstudio_mcp_demo/openstudio_mcp_server/runtime/`: workspace, artifact, job managers.
- `examples/openstudio_mcp_demo/skills/hvac_sizing_assistant.md`: skill prompt contract.
- `examples/openstudio_mcp_demo/policy/*.yaml`: allowlist and runtime gates.
