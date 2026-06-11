---
name: openstudio_hvac_workflow_state
description: Maintain persistent task-global HVAC workflow state for multi-phase OpenStudio model-editing workflows.
version: 0.2.0
output_format: markdown_with_json_state
---

## Scope

Use this skill whenever an OpenStudio HVAC creation or editing workflow spans
multiple phases, scripts, child skills, or clarification gates.

This skill defines the task-global parameter table that the parent workflow
skill must maintain. In OpenStudio AI, this state is persisted in the
session-scoped local JSON blackboard under `workflows.<workflow_id>`.

## Core Rule

The parent workflow skill owns the full state table and is the only workflow
role that writes blackboard state. Child skills and child script phases may only
read the current state and return a narrow state patch.

Do not let child skills independently re-ask global questions when the answer is
already present in the state table. If a required field is missing, the child
skill must report the missing field to the parent workflow.

## State Lifecycle

1. Initialize the state in the blackboard before the first script is drafted.
2. Update the blackboard state after preflight inspection.
3. Resolve missing required fields through one clarification gate whenever
   practical.
4. Before each child phase, show the subset of state that phase will use.
5. After each child phase, apply a state patch from the script result or tool
   result with `blackboard_write`.
6. Before final validation, show completed steps, pending steps, assumptions,
   created objects, and warnings.
7. Include the final blackboard state summary in the task answer.

## Blackboard Operations

Use these operations through `blackboard_read`, `blackboard_write`, and
`blackboard_get_revision`:

- `initialize_workflow`: create a safe `workflow_id`, set
  `active_workflow_id`, set `workflows.<workflow_id>` to the JSON state
  contract below, and append an `operation_log` item.
- `get_phase_state`: read `workflows.<workflow_id>` or a narrow path before
  loading a child skill.
- `update_state_patch`: normalize a child `state_patch`, merge it into
  `workflows.<workflow_id>`, update canonical lists such as `pending_steps`,
  and append an `operation_log` item.
- `mark_step_complete`: read the workflow, compute the new `completed_steps`
  and `pending_steps`, write both lists, and append an `operation_log` item.

Always write with `expected_revision` after reading. On a revision conflict,
re-read, re-apply the smallest intended patch, and retry once.

## Required State Table

Maintain this markdown table in the parent workflow response whenever practical.
Keep values short; use the JSON object below for full detail.

| Field | Value | Source | Status |
| --- | --- | --- | --- |
| `workflow_id` |  | generated | required |
| `input_model_path` |  | user/preflight | required |
| `current_model_path` |  | parent workflow | required |
| `output_model_path` |  | user/assumption | required |
| `system_name` |  | user/assumption | required |
| `target_zones` |  | user/preflight | required |
| `hvac_operation_schedule` |  | user/preflight/default | required |
| `oa_damper_schedule` |  | user/preflight/default | optional |
| `reheat_type` |  | user/assumption | required |
| `central_heating_type` |  | user/assumption | required |
| `central_cooling_type` |  | user/assumption | required |
| `hot_water_loop` |  | preflight/user | conditional |
| `chilled_water_loop` |  | preflight/user | conditional |
| `fan_pressure_rise` |  | user/assumption | required |
| `min_system_airflow_ratio` |  | user/assumption | required |
| `sizing_option` |  | user/assumption | required |
| `economizer_control_type` |  | user/assumption | optional |
| `return_plenum` |  | user/preflight | optional |
| `completed_steps` |  | parent workflow | required |
| `pending_steps` |  | parent workflow | required |
| `created_objects` |  | child phases | required |
| `assumptions` |  | parent/child phases | required |
| `warnings` |  | child phases | required |
| `validation_results` |  | validation phase | required |

## JSON State Contract

Use this JSON shape as the source of truth. Omit no top-level keys; use `null`,
empty arrays, or empty objects when values are unknown.

```json
{
  "workflow_id": "vav_reheat_001",
  "mode": "preflight|clarification|edit_phase|validation|simulation_handoff",
  "input_model_path": null,
  "current_model_path": null,
  "output_model_path": null,
  "openstudio_version": null,
  "standards_template": null,
  "system": {
    "system_name": null,
    "target_zone_names": [],
    "return_plenum_name": null,
    "existing_air_loop_conflict": null
  },
  "schedules": {
    "hvac_operation_schedule_name": null,
    "hvac_operation_schedule_source": null,
    "oa_damper_schedule_name": null,
    "oa_damper_schedule_source": null,
    "supply_air_temperature_schedule_name": null
  },
  "design_temperatures": {
    "preheat_supply_air_temp_f": 45.0,
    "precool_supply_air_temp_f": 55.0,
    "central_heating_supply_air_temp_f": 55.0,
    "central_cooling_supply_air_temp_f": 55.0,
    "zone_heating_supply_air_temp_f": 104.0,
    "zone_cooling_supply_air_temp_f": 55.0,
    "converted_to_si": false
  },
  "sizing": {
    "type_of_load_to_size_on": "Sensible",
    "minimum_system_airflow_ratio": 0.3,
    "sizing_option": "Coincident",
    "system_outdoor_air_method": "ZoneSum",
    "cooling_design_airflow_method": "DesignDay",
    "heating_design_airflow_method": "DesignDay"
  },
  "fan": {
    "fan_name": null,
    "fan_total_efficiency": 0.62,
    "fan_motor_efficiency": 0.9,
    "fan_pressure_rise_value": 4.0,
    "fan_pressure_rise_unit": "inH2O",
    "fan_pressure_rise_pa": null,
    "end_use_subcategory": "VAV System Fans"
  },
  "central_heating": {
    "type": null,
    "coil_name": null,
    "hot_water_loop_name": null,
    "rated_inlet_water_temperature_c": null,
    "rated_outlet_water_temperature_c": null,
    "rated_inlet_air_temperature_c": null,
    "rated_outlet_air_temperature_c": null
  },
  "central_cooling": {
    "type": null,
    "coil_name": null,
    "chilled_water_loop_name": null,
    "dx_fallback_approved": false
  },
  "outdoor_air_system": {
    "controller_name": null,
    "oa_system_name": null,
    "minimum_limit_type": "FixedMinimum",
    "economizer_control_type": null,
    "mechanical_ventilation_method": "ZoneSum"
  },
  "air_loop_controls": {
    "availability_schedule_name": null,
    "night_cycle_control_type": "CycleOnAny",
    "night_cycle_runtime_s": 1800
  },
  "zone_terminals": {
    "reheat_type": null,
    "terminal_names": [],
    "reheat_coil_names": [],
    "minimum_airflow_input_method": "Constant",
    "damper_heating_action": "Normal",
    "constant_minimum_airflow_fraction": null,
    "template_specific_damper_logic": null
  },
  "completed_steps": [],
  "pending_steps": [
    "preflight_inspection",
    "clarification_gate",
    "air_loop",
    "schedule_resolver",
    "sizing_system",
    "supply_fan",
    "central_heating_coil",
    "central_cooling_coil",
    "outdoor_air_system",
    "air_loop_controls",
    "zone_terminals",
    "validation",
    "simulation_handoff"
  ],
  "created_objects": {},
  "assumptions": [],
  "warnings": [],
  "validation_results": []
}
```

## Assumption Ledger

Every default or unresolved-but-approved value must be recorded in
`assumptions` using this exact format:

```text
Object:Name.parameter: assumed to be x
```

Examples:

```text
AirLoopHVAC:3 Zone VAV.sizing_option: assumed to be Coincident
FanVariableVolume:3 Zone VAV Fan.pressure_rise: assumed to be 4.0 inH2O
ControllerOutdoorAir:3 Zone VAV OA Controller.economizer_control_type: assumed to be OpenStudio default
```

## Child Phase Patch Contract

Each child skill or script phase must return a JSON patch with only the fields
it changed. The parent applies the patch to the full state.

```json
{
  "ok": true,
  "state_patch": {
    "completed_steps": ["supply_fan"],
    "pending_steps_remove": ["supply_fan"],
    "created_objects": {
      "fan": "3 Zone VAV Fan"
    },
    "fan": {
      "fan_name": "3 Zone VAV Fan",
      "fan_pressure_rise_pa": 995.4
    },
    "warnings": []
  }
}
```

The parent must normalize convenience keys such as `pending_steps_remove` into
the canonical `pending_steps` list before writing to the blackboard.

## Missing Field Behavior

If a child phase cannot proceed, it must return:

```json
{
  "ok": false,
  "missing_fields": [
    "central_heating.hot_water_loop_name"
  ],
  "clarifying_question": "Which existing hot-water plant loop should serve the water heating coils?"
}
```

The parent workflow should combine missing fields from multiple child phases
into one focused clarification gate whenever possible.

## Validation Expectations

Before simulation handoff, the state should confirm:

- input and output model paths are different unless overwrite was explicitly
  approved;
- all target zones were served by the new air loop;
- central coils are attached to the intended air-loop node;
- water coils are attached to the intended plant loop when water is used;
- terminal count equals target zone count;
- each created object name is recorded in `created_objects`;
- assumptions and warnings are included in the final response.
