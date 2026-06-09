---
name: openstudio_hvac_supply_fan_creator
description: Create and attach a variable-volume supply fan for an OpenStudio VAV air loop.
version: 0.1.0
output_format: markdown_with_json_state_patch
---

## Scope

Use this child skill to create the central variable-volume supply fan and add it
to the existing air-loop supply inlet node.

Do not create schedules, sizing systems, coils, outdoor-air systems, terminals,
simulations, or result queries in this skill.

## Required State Fields

- `current_model_path`
- `output_model_path`
- `created_objects.air_loop`
- `fan.fan_total_efficiency`
- `fan.fan_motor_efficiency`
- `fan.fan_pressure_rise_value`
- `fan.fan_pressure_rise_unit`
- `completed_steps`
- `pending_steps`

## Optional State Fields

- `fan.fan_name`
- `fan.end_use_subcategory`
- `fan.fan_pressure_rise_pa`
- `warnings`

## SDK Methods To Verify

- `FanVariableVolume.new`
- `FanVariableVolume.setName`
- `FanVariableVolume.setFanEfficiency`
- `FanVariableVolume.setMotorEfficiency`
- `FanVariableVolume.setPressureRise`
- `FanVariableVolume.setEndUseSubcategory`
- `FanVariableVolume.setAvailabilitySchedule`
- `FanVariableVolume.addToNode`
- `AirLoopHVAC.supplyInletNode`
- `Model.alwaysOnDiscreteSchedule`

## Code Pattern

1. Load `current_model_path` and find `created_objects.air_loop`.
2. Name the fan from `fan.fan_name` or default to `{air_loop_name} Fan`.
3. Convert pressure rise to Pa:
   - `Pa` stays unchanged;
   - `inH2O` converts with `249.08891 Pa/inH2O`.
4. Create `FanVariableVolume`.
5. Set fan total efficiency, motor efficiency, pressure rise, availability
   schedule, and end-use subcategory when the method is available.
6. Add the fan to `air_loop.supplyInletNode`.
7. Save and return the fan object name plus pressure conversion.

## Missing Field Behavior

Return missing fields for absent efficiency, motor efficiency, pressure value,
pressure unit, model paths, or air loop. If the unit is not `Pa` or `inH2O`,
ask for a supported unit or an explicit conversion.

## State Patch

```json
{
  "ok": true,
  "state_patch": {
    "current_model_path": "/path/to/output.osm",
    "completed_steps": ["supply_fan"],
    "pending_steps_remove": ["supply_fan"],
    "fan": {
      "fan_name": "3 Zone VAV Fan",
      "fan_pressure_rise_pa": 996.35564
    },
    "created_objects": {
      "fan": "3 Zone VAV Fan"
    },
    "warnings": []
  }
}
```

## Validation Checks

- Fan exists with expected name.
- Fan is connected to the target air-loop supply inlet node.
- Pressure rise is stored in Pa in the model and in state.
