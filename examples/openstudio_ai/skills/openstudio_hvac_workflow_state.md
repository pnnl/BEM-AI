---
name: openstudio_hvac_workflow_state
description: Maintain persistent task-global HVAC workflow state for multi-phase OpenStudio model-editing workflows.
version: 0.3.0
output_format: markdown_with_json_state
---

## Scope

Use this skill whenever an OpenStudio HVAC creation/editing workflow spans
multiple phases, child skills, scripts, or clarification gates.

OpenStudio AI persists workflow state in the session blackboard under
`workflows.<workflow_id>`. The parent workflow skill owns all writes. Child
skills and script phases return narrow `state_patch` objects only.

## Parent Rules

- Read the active workflow before planning a phase.
- Write state only through `blackboard_write` with `expected_revision`.
- Normalize child patch convenience keys before writing.
- Do not let child skills re-ask values already present in state.
- If a required value is missing, ask one focused clarification question and
  write the answer before continuing.
- Include a compact final state summary in the task answer.

## Blackboard Operations

- `initialize_workflow`: create `workflow_id`, set `active_workflow_id`, set
  `workflows.<workflow_id>`, append `operation_log`.
- `get_phase_state`: read the active workflow or narrow phase paths before
  loading a child skill.
- `update_state_patch`: merge a normalized child `state_patch` into
  `workflows.<workflow_id>` and append `operation_log`.
- `mark_step_complete`: update canonical `completed_steps` and `pending_steps`
  lists and append `operation_log`.

On revision conflict, re-read the workflow, re-apply the smallest intended
patch, and retry once.

## Canonical Workflow Fields

Every workflow should keep these top-level fields. Use `null`, empty arrays, or
empty objects for unknown values.

```text
workflow_id
mode
input_model_path
current_model_path
output_model_path
openstudio_version
standards_template
system
schedules
design_temperatures
sizing
fan
central_heating
central_cooling
outdoor_air_system
air_loop_controls
zone_terminals
completed_steps
pending_steps
created_objects
assumptions
warnings
validation_results
missing_fields
last_phase
```

Default VAV pending steps:

```text
preflight_inspection
clarification_gate
air_loop
schedule_resolver
sizing_system
supply_fan
central_heating_coil
central_cooling_coil
outdoor_air_system
air_loop_controls
zone_terminals
validation
simulation_handoff
```

## Assumption Ledger

Record every approved default in `assumptions` using:

```text
Object:Name.parameter: assumed to be x
```

## Child Patch Contract

Each child phase returns only changed fields:

```json
{
  "ok": true,
  "state_patch": {
    "completed_steps": ["supply_fan"],
    "pending_steps_remove": ["supply_fan"],
    "created_objects": {"fan": "3 Zone VAV Fan"},
    "fan": {"fan_name": "3 Zone VAV Fan", "fan_pressure_rise_pa": 995.4},
    "warnings": []
  }
}
```

The parent must convert `pending_steps_remove` into the canonical
`pending_steps` list before writing to the blackboard.

If blocked, a child phase returns:

```json
{
  "ok": false,
  "missing_fields": ["central_heating.hot_water_loop_name"],
  "clarifying_question": "Which existing hot-water plant loop should serve the water heating coils?"
}
```

## Validation Before Handoff

Before simulation handoff, confirm in state:

- input and output paths are distinct unless overwrite was approved;
- target zones are served by the new air loop;
- central and reheat water coils are attached to intended plant loops;
- terminal count equals target zone count;
- created object names, assumptions, warnings, and validation results are
  recorded.
