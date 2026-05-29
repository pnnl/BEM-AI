# OpenStudio MCP Demo

This example shows a YAML-defined AUTOMA-AI agent connected to a real MCP server
that exposes a minimal OpenStudio modeling/simulation lifecycle. It also gives
the agent a bounded `run_python` workspace for OpenStudio Python SDK model
inspection and model editing. The Python bootstrap still starts the MCP and A2A
servers, but the agent card, model, runtime settings, tools, MCP client
connection, skills, and instructions live in YAML.

## What is `openstudio_mcp`?

`openstudio_mcp` is a real MCP server (Anthropic `mcp`/`FastMCP`) that exposes OpenStudio workflows as MCP tools for AUTOMA-AI agents.

It provides:

- `model_*` tools for model lifecycle operations.
- `sim_*` tools for asynchronous OpenStudio simulation execution.
- `results_*` tools for SQL-backed post-processing and summarization.
- `sdk_docs_*` tools for deterministic lookup against local OpenStudio SDK HTML
  documentation.

The intended split is:

- MCP = curated, production workflow tools for simulations, artifacts, and
  results retrieval.
- `run_python` + OpenStudio Python SDK = flexible local model-inspection and
  model-editing workspace.
- `sdk_docs_*` = exact API lookup for SDK constructors, getters, setters,
  parameter types, units, and warnings before drafting scripts.
- Skills = reusable deterministic modeling workflows and guardrails.

## Architecture

The example has four layers:

1. Agent layer
- `examples/openstudio_mcp_demo/agent.py`
- Loads `specs/openstudio_agent.yaml` with `load_a2a_server_from_yaml(...)`.
- Connects to MCP and orchestrates MCP tool calls plus bounded `run_python`
  model-inspection/model-editing scripts.

2. MCP server layer
- `examples/openstudio_mcp_demo/openstudio_mcp_server/server.py`
- Registers model/sim/results/sdk-docs MCP tools.
- Uses standard MCP success/error envelope.

3. Runtime/state layer
- `runtime/workspace_manager.py`: per-job sandbox folders and quota checks.
- `runtime/job_manager.py`: `RUNNING/SUCCEEDED/FAILED` lifecycle.
- `runtime/artifact_store.py`: immutable artifact IDs and metadata.
- `runtime/measure_registry.py`: policy-based measure lookup and arg validation.

4. Governance/extension layer
- `specs/openstudio_agent.yaml`
- `prompts/openstudio_agent.md`
- `policy/tool_allowlist.yaml`
- `policy/run_gates.yaml`
- `policy/measure_registry.yaml`
- `skills/hvac_sizing_assistant.md`
- `skills/openstudio_sdk_model_editor.md`
- `knowledge/openstudio_sdk_recipes.md`
- `knowledge/openstudio_sdk_wiki/`, including routing, domain packs, and review
  prompts.

## Capabilities

### Model inspection and editing workspace

- Use `run_python` only for local OpenStudio Python SDK scripts that inspect or
  edit `.osm` files.
- Edited models should be saved as copies under `outputs/` or another
  user-approved path.
- Do not use `run_python` for simulations, polling, SQL result retrieval,
  subprocesses, shell commands, or network calls.

### Model tools

- `model_load(model_uri)`
- `model_clone(model_id)`
- `model_list_measures()`
- `model_set_weather(model_id, epw_path)`
- `model_set_design_days(model_id, ddy_id | derive_from_epw=true)` (compatibility step)
- `model_apply_measure(model_id, measure_id, args)`
- `model_validate(model_id)`

### Simulation tools

- `sim_run(model_id, run_mode, options)` returns `job_id` immediately.
- `sim_status(job_id)` supports polling asynchronous simulation.
- `sim_artifacts(job_id)` returns result artifact IDs.

### Results tools

`results_query(sql_id, query_type, params)` supports:

- `annual_end_use_fuel`
- `design_day_end_use_fuel`
- `annual_eui`
- `sizing_summary`

`results_summarize(data, format)` returns readable summary text/tables.

### SDK documentation tools

The optional `sdk_docs_*` tools inspect local Doxygen-generated OpenStudio SDK
HTML documentation. Set `OPENSTUDIO_SDK_DOCS_DIR` to the directory containing
`classopenstudio_1_1model_*.html` files.

- `sdk_docs_route(query)`: identify likely SDK wiki packs and OpenStudio model
  classes for an SDK scripting request.
- `sdk_docs_find_classes(query)`: find model SDK classes by name or keyword.
- `sdk_docs_list_methods(class_name, keyword)`: list methods on a class.
- `sdk_docs_get_method(class_name, method_name, anchor=None,
  signature_contains=None)`: return exact signature, docs, unit notes, and a
  local source URL for a method. Use `anchor` or `signature_contains` when the
  SDK docs show multiple overloads for the same method name.
- `sdk_docs_search_methods(keyword, class_filter)`: search method names across
  model classes.

You can build a local cache summary for inspection:

```bash
python3 examples/openstudio_mcp_demo/scripts/build_sdk_doc_index.py \
  --docs-dir /path/to/openstudio-sdk-html \
  --output examples/openstudio_mcp_demo/.sdk_doc_index.json
```

The generated cache is ignored by git.

## Setup

1. Copy `sample.env` to `.env`.
2. Update model and server settings as needed.
3. Set `OPENSTUDIO_PATH` to the local OpenStudio CLI executable path.
4. Ensure the Python executable configured in `specs/openstudio_agent.yaml` can
   import the OpenStudio Python SDK when using SDK inspection/editing. If needed,
   update `tools.tools[0].config.python_executable`.
5. Optional but recommended: set `OPENSTUDIO_SDK_DOCS_DIR` to local OpenStudio
   SDK HTML documentation so the agent can verify exact SDK APIs before writing
   scripts.

## YAML Agent Spec

The agent is defined in:

- `examples/openstudio_mcp_demo/specs/openstudio_agent.yaml`

The spec points to:

- `prompts/openstudio_agent.md` for the system instruction.
- `skills/hvac_sizing_assistant.md` for the deterministic MCP sizing workflow.
- `skills/openstudio_sdk_model_editor.md` for bounded SDK inspection/editing.
- `knowledge/openstudio_sdk_wiki/` as dynamically loadable SDK example packs.
- The `openstudio_mcp` MCP client connection.
- A built-in `run_python` tool rooted at the example directory.
- `logs/telemetry.jsonl` for local JSONL agent telemetry. The demo uses the
  built-in recorder only and does not load telemetry recorder plugins.
- `logs/python_script_failure_experience.jsonl` for failed Python script
  executions that can be reviewed by a separate learning/summarization process.
- The A2A 1.0 card shape with `supportedInterfaces`.

`agent.py` applies environment-specific overrides from `.env` at startup:

- `CHATBOT_SERVER_URL`
- `CHAT_BOT_MODEL_NAME`
- `CHAT_BOT_MODEL_BASE_URL`
- `OPENSTUDIO_MCP_HOST`
- `OPENSTUDIO_MCP_PORT`
- `OPENSTUDIO_SDK_DOCS_DIR`

## Run

- Start agent server + MCP server:
  - `python3 examples/openstudio_mcp_demo/agent.py`
- Optional Streamlit UI:
  - `streamlit run examples/openstudio_mcp_demo/ui.py`
  - The UI includes a right-side telemetry panel that reads
    `logs/telemetry.jsonl` and renders recent spans/events as an expandable
    trace tree.
- Combined launcher:
  - `bash examples/openstudio_mcp_demo/run_all.sh`

## Troubleshooting

- If MCP tools are unavailable, confirm MCP server startup log in `examples/openstudio_mcp_demo/logs/server.log`.
- If chat responses stall, confirm the configured LLM endpoint/model is available.
- If `sim_run` fails, verify `OPENSTUDIO_PATH` points to a valid OpenStudio executable and ensure the model contains a valid `OS:WeatherFile` path (or pass one via `model_set_weather` / `sim_run` options with `epw_path`).
- Simulation runtime files are generated under `.openstudio_mcp_workspace/<job_id>/` (including `run/eplusout.sql`).
- If `model_apply_measure` fails, verify `policy/measure_registry.yaml` contains an allowed entry and the script exists under `measures/`.

## Results Query Types

`results_query` now reads real data from `eplusout.sql` and supports:

- `annual_end_use_fuel`: Annual end-use by fuel matrix from `AnnualBuildingUtilityPerformanceSummary -> End Uses`.
- `design_day_end_use_fuel`: Design-day energy by end-use/fuel from `ReportMeterDataDictionary` + `ReportMeterData`.
- `annual_eui`: Total site energy and EUI (kBtu/ft²) derived from SQL tabular outputs.
- `sizing_summary`: Consolidated payload including all three query outputs above.

## Measures

- Measure registry policy: `examples/openstudio_mcp_demo/policy/measure_registry.yaml`
- Built-in measure: `add_daylighting` (`examples/openstudio_mcp_demo/measures/add_daylighting.py`)
- Discover measures at runtime with `model_list_measures`.
- `model_apply_measure` resolves `measure_id` via policy, validates args/defaults, executes with:
  - `openstudio execute_python_script <entrypoint>`
  - environment variables `OSM_INPUT_PATH`, `OSM_OUTPUT_PATH`, `MEASURE_ARGS_JSON`
- On success, a new model artifact/state is created and returned as `model_id`.

### Measure interface contract

`model_apply_measure` is policy-driven:

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

- `examples/openstudio_mcp_demo/agent.py`: YAML-backed MCP and A2A bootstrap.
- `examples/openstudio_mcp_demo/specs/openstudio_agent.yaml`: YAML agent spec.
- `examples/openstudio_mcp_demo/prompts/openstudio_agent.md`: YAML agent instruction.
- `examples/openstudio_mcp_demo/skills/openstudio_sdk_model_editor.md`: run_python + SDK model-inspection/editing workflow.
- `examples/openstudio_mcp_demo/knowledge/openstudio_sdk_recipes.md`: lightweight SDK knowledge-base entry point and routing summary.
- `examples/openstudio_mcp_demo/knowledge/openstudio_sdk_wiki/`: loadable SDK context packs distilled from OpenStudio standards and source-reviewed Python SDK usage.
- `examples/openstudio_mcp_demo/OPENSTUDIO_SDK_EXPERIENCE.md`: human-readable source-review note for OpenStudio SDK usage patterns.
- `examples/openstudio_mcp_demo/architecture_diagram.md`: Sponsor-friendly architecture/workflow diagrams.
- `examples/openstudio_mcp_demo/ADVANCED_USER_GUIDE.md`: Advanced extension guide for measures, policies, and skills.
- `examples/openstudio_mcp_demo/openstudio_mcp_server/server.py`: MCP server entrypoint.
- `examples/openstudio_mcp_demo/openstudio_mcp_server/sdk_docs/`: local SDK HTML parser and lookup helper.
- `examples/openstudio_mcp_demo/openstudio_mcp_server/tools/`: model/sim/results/sdk-docs tools.
- `examples/openstudio_mcp_demo/openstudio_mcp_server/runtime/`: workspace, artifact, job managers.
- `examples/openstudio_mcp_demo/scripts/build_sdk_doc_index.py`: optional SDK doc index builder.
- `examples/openstudio_mcp_demo/skills/hvac_sizing_assistant.md`: skill prompt contract.
- `examples/openstudio_mcp_demo/policy/*.yaml`: allowlist and runtime gates.
