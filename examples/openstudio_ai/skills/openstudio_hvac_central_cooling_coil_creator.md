---
name: openstudio_hvac_central_cooling_coil_creator
description: Create the central cooling coil for an OpenStudio VAV air loop, with chilled-water or approved DX fallback options.
version: 0.1.0
output_format: markdown_with_json_state_patch
---

## Scope

Use this child skill to create the central cooling coil for the VAV air loop. It
supports chilled-water coils and explicit DX fallback when no chilled-water loop
is selected.

Do not create the air loop, fan, heating coil, outdoor-air system, terminals,
simulations, or result queries in this skill.

## Required State Fields

- `current_model_path`
- `output_model_path`
- `created_objects.air_loop`
- `central_cooling.type`
- `completed_steps`
- `pending_steps`

Conditional required fields:

- `central_cooling.chilled_water_loop_name` when `central_cooling.type` is
  `Water`
- `central_cooling.dx_fallback_approved` when a DX coil is requested

## Optional State Fields

- `central_cooling.coil_name`
- `warnings`

## SDK Methods To Verify

- `CoilCoolingWater.new`
- `PlantLoop.addDemandBranchForComponent`
- `HVACComponent.addToNode`
- `AirLoopHVAC.supplyInletNode`
- selected DX cooling coil constructor, usually the local pattern equivalent of
  `create_coil_cooling_dx_two_speed`
- any DX curve constructor or default curve requirements for the active SDK

## Code Pattern

1. Load `current_model_path` and find the air loop.
2. If type is `Water`, find `central_cooling.chilled_water_loop_name`, create
   `CoilCoolingWater`, attach it to the loop demand side, then add it to the
   air-loop supply inlet node.
3. If type is `DXTwoSpeed` or another DX fallback, require
   `dx_fallback_approved: true`; then create the selected DX coil with explicit
   default curve handling.
4. Save and return coil object details.

## Missing Field Behavior

If a water coil is requested without a chilled-water loop name, ask which
existing chilled-water plant loop should serve the coil. If DX fallback is
requested without approval, ask for explicit approval and identify the selected
DX class.

## State Patch

```json
{
  "ok": true,
  "state_patch": {
    "current_model_path": "/path/to/output.osm",
    "completed_steps": ["central_cooling_coil"],
    "pending_steps_remove": ["central_cooling_coil"],
    "central_cooling": {
      "type": "Water",
      "coil_name": "3 Zone VAV Clg Coil",
      "chilled_water_loop_name": "Chilled Water Loop"
    },
    "created_objects": {
      "central_cooling_coil": "3 Zone VAV Clg Coil"
    },
    "warnings": []
  }
}
```

## Validation Checks

- Requested cooling-coil type was created exactly once.
- Chilled-water coil is attached to the named plant loop demand side.
- Cooling coil is added to the target air-loop supply inlet node.
- DX fallback is never used silently.
