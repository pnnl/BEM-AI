---
name: openstudio_hvac_schedule_resolver
description: Resolve or create HVAC operation, outdoor-air damper, and supply-air temperature schedules for OpenStudio HVAC workflows.
version: 0.1.0
output_format: markdown_with_json_state_patch
---

## Scope

Use this child skill to resolve schedule inputs for a phased HVAC workflow. It
may reuse existing schedules, create approved default schedules, and create the
constant supply-air temperature schedule used by the VAV supply outlet setpoint
manager.

Do not create the air loop, the fan, coils, the outdoor-air controller, terminals, simulations, result queries in this skill.

## Required State Fields

- `current_model_path`
- `output_model_path`
- `system.system_name`
- `schedules.hvac_operation_schedule_name`
- `design_temperatures.central_cooling_supply_air_temp_f`
- `completed_steps`
- `pending_steps`



## Optional State Fields

- `schedules.oa_damper_schedule_name`
- `schedules.hvac_operation_schedule_source`
- `schedules.oa_damper_schedule_source`
- `schedules.supply_air_temperature_schedule_name`
- `assumptions`
- `warnings`


## SDK Methods To Verify

Verify constructors and setters before drafting code:

- `Model.alwaysOnDiscreteSchedule`
- `Model.getScheduleRulesets` or relevant schedule collection getter
- `ScheduleRuleset.setName`
- `ScheduleTypeLimits`
- `SetpointManagerScheduled.new`
- `SetpointManagerScheduled.setName`
- `SetpointManagerScheduled.addToNode`
- `AirLoopHVAC.supplyOutletNode` when attaching the setpoint manager in this phase


## Code Pattern

1. Load `current_model_path`.
2. Resolve the HVAC operation schedule:
   - if the state names an existing schedule, retrieve it;
   - if the parent approved the default, use `model.alwaysOnDiscreteSchedule`.
   
3. Resolve the optional outdoor-air damper schedule:
   - retrieve the named schedule when present;
   - otherwise leave it unset and record that status.
   
4. Create a constant supply-air temperature schedule using the central cooling
   supply-air design temperature converted to SI.
   
5. If `created_objects.air_loop` exists and the parent assigns this phase to
   setpoint-manager attachment, create `SetpointManagerScheduled` and add it to
   the air-loop supply outlet node.
   
6. Save to `output_model_path` and update `current_model_path`.


## Missing Field Behavior

If a named schedule cannot be found, return `ok: false` with the missing field
and candidate schedule names.

If the HVAC operation schedule is missing and no default was approved, ask
whether to use Always On Discrete.

## State Patch

Return only changed fields:

```json
{
  "ok": true,
  "state_patch": {
    "current_model_path": "/path/to/output.osm",
    "completed_steps": [
      "schedule_resolver"
    ],
    "pending_steps_remove": [
      "schedule_resolver"
    ],
    "schedules": {
      "hvac_operation_schedule_name": "Always On Discrete",
      "hvac_operation_schedule_source": "default",
      "oa_damper_schedule_name": null,
      "oa_damper_schedule_source": "unset",
      "supply_air_temperature_schedule_name": "Supply Air Temp - 55.0F"
    },
    "created_objects": {
      "supply_air_temperature_schedule": "Supply Air Temp - 55.0F",
      "supply_air_setpoint_manager": "3 Zone VAV Supply Air Setpoint Manager"
    },
    "assumptions": [
      "Schedule:Always On Discrete.hvac_operation_schedule: assumed to be default"
    ],
    "warnings": []
  }
}
```

## Validation Checks

- Every named schedule in state resolves to exactly one model object.
- Created temperature schedule stores SI values and records the originating F value in the state.
- Setpoint manager is attached only when the target air loop exists.


