# OpenStudio MCP Demo: Advanced User Guide

This guide is for advanced users who want to extend the OpenStudio MCP server with custom measures, policies, and skills.

## Who this is for

- You can read/write Python.
- You are comfortable with OpenStudio model concepts.
- You want to customize behavior beyond the default demo workflow.

## Extension Surface

You will typically work in three areas:

1. Measures: Add new OpenStudio transformations through `model_apply_measure`.
2. Policies: Control what is allowed and how it is validated.
3. Skills: Improve agent orchestration and tool usage quality.

---

## 1) Add a New Measure

### 1.1 Create the measure script

Add a Python script under:

- `examples/openstudio_mcp_demo/measures/`

Follow the contract used by `add_daylighting.py`:

- Inputs from env vars:
  - `OSM_INPUT_PATH`
  - `OSM_OUTPUT_PATH`
  - `MEASURE_ARGS_JSON`
- Load OSM with OpenStudio API.
- Apply changes.
- Save output model to `OSM_OUTPUT_PATH`.
- Print one final JSON line to stdout with at least:
  - `ok`
  - `changes`
  - `warnings`

If the script exits non-zero or does not produce output OSM, MCP treats it as failed.

### 1.2 Register measure in policy

Edit:

- `examples/openstudio_mcp_demo/policy/measure_registry.yaml`

Add an entry:

- `measure_id`
- `entrypoint` (relative to `examples/openstudio_mcp_demo/`)
- `description`
- `allowed`
- `timeout_seconds`
- `args_schema` (JSON-schema-like fields used for defaults/type checks)

### 1.3 Discover and call measure

At runtime:

1. Call `model_list_measures`.
2. Pick `measure_id` and inspect `args_schema`.
3. Call `model_apply_measure(model_id, measure_id, args)`.
4. Use returned `model_id` for downstream steps.

Note: `model_apply_measure` returns a new model id (immutable artifact style), not in-place mutation.

---

## 2) Policy Customization

### 2.1 Measure policy

File:

- `examples/openstudio_mcp_demo/policy/measure_registry.yaml`

What to control:

- Governance: set `allowed: false` to disable risky measures.
- Runtime: set `timeout_seconds` per measure.
- Input quality: tighten `args_schema` types/defaults.

Recommended practice:

- Keep defaults conservative.
- Require explicit values for potentially high-impact fields.

### 2.2 Tool allowlist policy

File:

- `examples/openstudio_mcp_demo/policy/tool_allowlist.yaml`

Use this to constrain which MCP tool prefixes are callable by the agent.

### 2.3 Runtime gates policy

File:

- `examples/openstudio_mcp_demo/policy/run_gates.yaml`

Use this to limit run budgets (`max_runtime_minutes`, `max_variants`) in agent workflows.

---

## 3) Skill Engineering for Better Tool Use

File:

- `examples/openstudio_mcp_demo/skills/hvac_sizing_assistant.md`

Use skills to enforce robust behavior:

- Always call `model_list_measures` before `model_apply_measure`.
- Prefer explicit assumptions in output.
- Require `sim_status` polling before querying artifacts/results.
- Include artifact IDs in final answer.

Skill quality checklist:

- Keep steps deterministic.
- Keep tool names explicit.
- Define failure handling for each stage.

---

## 4) Recommended Dev Workflow

1. Edit measure script.
2. Update `measure_registry.yaml` entry.
3. Start MCP + agent.
4. Run focused tests.
5. Run end-to-end sizing flow.

Useful command:

```bash
uv run pytest -q tests/test_mcp_openstudio_smoke.py
```

---

## 5) Debugging

### Measure failures

Check logs in the measure workspace:

- `.openstudio_mcp_workspace/measure-<id>/measure.stdout.log`
- `.openstudio_mcp_workspace/measure-<id>/measure.stderr.log`

### Simulation failures

Check job workspace:

- `.openstudio_mcp_workspace/<job_id>/run/eplusout.err`
- `.openstudio_mcp_workspace/<job_id>/run/eplusout.end`
- `.openstudio_mcp_workspace/<job_id>/run/eplusout.sql`

### Common causes

- Bad `OPENSTUDIO_PATH`.
- Missing/invalid weather path.
- Measure script writes malformed JSON or no output model.
- Policy disallows measure id.

---

## 6) Design Rules for Advanced Extensions

- Prefer immutable model artifacts (new model id per transformation).
- Keep measure scripts side-effect free outside workspace.
- Treat policy as source of truth for allowed actions.
- Keep tool IO structured and machine-parseable.
- Add tests for every new measure and policy rule.

---

## 7) Minimal Template for a New Measure

```python
# examples/openstudio_mcp_demo/measures/my_measure.py
import json
import os
import sys
import openstudio


def main() -> int:
    input_path = os.getenv("OSM_INPUT_PATH", "")
    output_path = os.getenv("OSM_OUTPUT_PATH", "")
    args = json.loads(os.getenv("MEASURE_ARGS_JSON", "{}"))

    translator = openstudio.openstudioosversion.VersionTranslator()
    m = translator.loadModel(str(input_path))
    if not m.is_initialized():
        print(json.dumps({"ok": False, "error": "Failed to load model."}))
        return 2
    model = m.get()

    # apply model changes here...

    if not model.save(str(output_path), True):
        print(json.dumps({"ok": False, "error": "Failed to save model."}))
        return 2

    print(json.dumps({"ok": True, "changes": ["Applied my_measure"], "warnings": []}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

## 8) Suggested Next Improvements

- Add schema-level enum constraints for measure argument options.
- Add policy-level max file size / max runtime safeguards per measure class.
- Add a `model.diff` tool to summarize what changed between two model ids.
