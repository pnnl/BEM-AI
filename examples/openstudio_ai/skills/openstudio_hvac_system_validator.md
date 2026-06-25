---
name: openstudio_hvac_system_validator
description: Validate object counts, connections, assumptions, and output state for a phased OpenStudio HVAC workflow.
version: 0.1.0
output_format: markdown_with_json_state_patch
---

## Scope

Use this child skill after model-editing phases and before simulation handoff.
It validates the edited `.osm` and summarizes whether the state table matches
the model.

Do not create HVAC objects except for read-only validation metadata in the returned state patch, simulations, SQL result queries in this skill.

## Required State Fields

- `current_model_path`
- `output_model_path`
- `created_objects.air_loop`
- `system.target_zone_names`
- `completed_steps`
- `pending_steps`
- `created_objects`
- `assumptions`
- `warnings`



## Optional State Fields

- `central_heating`
- `central_cooling`
- `outdoor_air_system`
- `zone_terminals`
- `validation_results`


## SDK Methods To Verify

- `Model.getAirLoopHVACs`
- `AirLoopHVAC.thermalZones`
- `AirLoopHVAC.supplyComponents`
- `AirLoopHVAC.demandComponents`
- `Model.getThermalZones`
- `ThermalZone.equipment`
- `PlantLoop.demandComponents`
- `Model.save`


## Code Pattern

1. Load `current_model_path` read-only unless the parent explicitly requests a saved validation copy.
2. Confirm the air loop exists.
3. Confirm all `system.target_zone_names` are served by the air loop.
4. Confirm fan, central coils, OA controller/system, terminals, and reheat coils recorded in `created_objects` exist in the model when those phases were completed.
5. Confirm water coils are connected to the named plant loops when water types were used.
6. Confirm terminal count equals target zone count.
7. Confirm `current_model_path` and `output_model_path` are consistent.
8. Return pass/fail validation items and unresolved warnings.


## Missing Field Behavior

If required state is absent, return missing fields rather than guessing from the model.

If the model path cannot be loaded, return a hard validation failure.

## State Patch

Return only changed fields:

```json
{
  "ok": true,
  "state_patch": {
    "completed_steps": [
      "validation"
    ],
    "pending_steps_remove": [
      "validation"
    ],
    "validation_results": [
      {
        "check": "served_zones",
        "ok": true,
        "detail": "All 3 target zones are served by 3 Zone VAV."
      }
    ],
    "warnings": []
  }
}
```

## Validation Checks

- Validation results record pass/fail items with enough detail to debug the workflow state.
- Unresolved warnings remain in the returned state patch instead of being dropped.



## Validation Result Format

```json
{
  "check": "terminal_count",
  "ok": true,
  "detail": "3 terminals found for 3 target zones."
}
```



## Handoff Rule

When validation passes or only accepted warnings remain, return control to the
parent workflow for MCP `model_*`, `sim_*`, and `results_*` handoff.


