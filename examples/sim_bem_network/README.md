# sim_bem_network

This example demonstrates the current multi-agent AUTOMA-AI pattern for OpenStudio building energy modeling:

- one coordinator agent built with `AgentFactory`
- specialist subagents connected with `SubAgentSpec`
- MCP servers for OpenStudio model generation and model manipulation
- a shared local JSON blackboard for task state, model paths, simulation state, and outputs

It replaces the older network/orchestrator workflow graph pattern.

## Architecture

Agents:

- `BEM Coordinator Agent` at `http://localhost:10001/`
- `Planner Agent` at `http://localhost:10102/`
- `Energy Model Envelope Agent` at `http://localhost:10103/`
- `Energy Model Lighting Agent` at `http://localhost:10104/`
- `Energy Model Generator Agent` at `http://localhost:10105/`
- `Energy Simulation Agent` at `http://localhost:10106/`
- `Energy Output Agent` at `http://localhost:10107/`

MCP servers:

- `oss_schema_mcp` at `http://localhost:10110/`
- `oss_model_mcp` at `http://localhost:10118/`

Shared state:

- local JSON blackboard under `examples/sim_bem_network/.demo_blackboards/`

## Files

- [sim_bem_network_orchestrator.py](./sim_bem_network_orchestrator.py): server bootstrap
- [streamlit_ui.py](./streamlit_ui.py): chat UI
- [agent_cards](./agent_cards): plain JSON agent cards
- [app_mcps/model_mcp.py](./app_mcps/model_mcp.py): model-template MCP server
- [app_mcps/os_mcp.py](./app_mcps/os_mcp.py): OpenStudio modification and simulation MCP server

## Setup

Prerequisites:

- Python 3.12+
- `streamlit`
- `openstudio`
- a working OpenStudio CLI path in `.env`

Create `.env` from [example.env](./example.env) and set:

- `PLANNER_MODEL_NAME`
- `PLANNER_MODEL_BASE_URL` if needed
- `SPECIALIZED_AGENT_MODEL_NAME`
- `OPENSTUDIO_APPLICATION_PATH`

Update the sample OSM weather file paths in `examples/sim_bem_network/app_mcps/models/*.osm` so they point to valid local EPW files.

## Run

Recommended:

```bash
cd examples/sim_bem_network
chmod +x run_all.sh
./run_all.sh
```

Manual:

```bash
cd examples/sim_bem_network
python sim_bem_network_orchestrator.py
```

Then in another terminal:

```bash
cd examples/sim_bem_network
streamlit run streamlit_ui.py
```

## Example prompts

- `Generate a medium office model for Tampa Florida using ASHRAE 90.1 2019 and evaluate the impact of reducing window-to-wall ratio by 10%.`
- `Use my existing OpenStudio model at /path/to/model.osm, add daylighting sensors, run a simulation, and report annual site EUI.`

## Troubleshooting

- If the server does not start, check `logs/server.log`.
- If the UI cannot connect, confirm the coordinator is listening on `http://localhost:10001/`.
- If model generation fails, confirm the sample model weather file paths are valid.
- If simulation fails, confirm `OPENSTUDIO_APPLICATION_PATH` points to a valid OpenStudio CLI.
- If the example cannot be imported in a minimal environment, that is usually because `openstudio` is not installed.
