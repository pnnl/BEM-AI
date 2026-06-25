---
name: openstudio_hvac_air_loop_creator
description: Create or confirm the parent AirLoopHVAC object for a phased OpenStudio HVAC workflow.
version: 0.1.0
output_format: markdown_with_json_state_patch
---

## Scope

Use this child skill only for the air-loop shell in a phased HVAC workflow. It
creates or confirms the `AirLoopHVAC`, records its name, and returns a
`state_patch` to the parent workflow.

Do not create schedules, sizing objects, fans, coils, outdoor-air systems, zone terminals, simulations, result queries in this skill.

## Required State Fields

- `current_model_path`
- `output_model_path`
- `system.system_name`
- `system.target_zone_names`
- `completed_steps`
- `pending_steps`



## Optional State Fields

- `openstudio_version`
- `system.existing_air_loop_conflict`
- `created_objects.air_loop`
- `warnings`


## SDK Methods To Verify

Before drafting code, verify these exact SDK calls through `sdk_docs_get_method`
or targeted Python binding introspection:

- `OpenStudio::Model::AirLoopHVAC.new`
- `AirLoopHVAC.setName`
- `Model.getAirLoopHVACs`
- `AirLoopHVAC.name`


## Code Pattern

1. Load `current_model_path`.
2. If an air loop named `system.system_name` already exists, do not create a
   duplicate. Return a warning and mark the loop as confirmed only if the parent
   approved reuse.
   
3. Otherwise create `AirLoopHVAC`, set its name, save to `output_model_path`,
   and update `current_model_path` to that path.
   
4. Keep this script short and inspectable.


## Missing Field Behavior

Return a missing-field envelope if `system.system_name`, `current_model_path`, or
`output_model_path` is absent.

If target zones are empty, report `system.target_zone_names`; the air loop can
technically be created without branches, but the parent workflow should confirm
scope first.

## State Patch

Return only changed fields:

```json
{
  "ok": true,
  "state_patch": {
    "current_model_path": "/path/to/output.osm",
    "completed_steps": [
      "air_loop"
    ],
    "pending_steps_remove": [
      "air_loop"
    ],
    "created_objects": {
      "air_loop": "3 Zone VAV"
    },
    "system": {
      "existing_air_loop_conflict": false
    },
    "warnings": []
  }
}
```

## Validation Checks

- Exactly one air loop with the requested name exists.
- The output model path exists and differs from the input path unless overwrite was explicitly approved by the parent.
- No terminal branches or supply components were added by this phase.


