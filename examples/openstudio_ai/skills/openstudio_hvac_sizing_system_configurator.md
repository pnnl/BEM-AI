---
name: openstudio_hvac_sizing_system_configurator
description: Configure AirLoopHVAC SizingSystem and standard design temperatures for OpenStudio VAV workflows.
version: 0.1.0
output_format: markdown_with_json_state_patch
---

## Scope

Use this child skill to configure `SizingSystem` and design sizing temperature
values on an existing air loop. It mirrors the sizing portion of
`model_add_vav_reheat`.

Do not create the air loop, the fan, coils, the outdoor-air system, terminals, simulations, result queries in this skill.

## Required State Fields

- `current_model_path`
- `output_model_path`
- `created_objects.air_loop`
- `design_temperatures`
- `sizing.minimum_system_airflow_ratio`
- `sizing.sizing_option`
- `completed_steps`
- `pending_steps`



## Optional State Fields

- `openstudio_version`
- `sizing.type_of_load_to_size_on`
- `sizing.system_outdoor_air_method`
- `sizing.cooling_design_airflow_method`
- `sizing.heating_design_airflow_method`
- `warnings`


## SDK Methods To Verify

- `AirLoopHVAC.sizingSystem`
- `SizingSystem.setTypeofLoadtoSizeOn`
- `SizingSystem.autosizeDesignOutdoorAirFlowRate`
- `SizingSystem.setPreheatDesignTemperature`
- `SizingSystem.setPrecoolDesignTemperature`
- `SizingSystem.setCentralCoolingDesignSupplyAirTemperature`
- `SizingSystem.setCentralHeatingDesignSupplyAirTemperature`
- `SizingSystem.setCentralHeatingMaximumSystemAirFlowRatio`
- `SizingSystem.setMinimumSystemAirFlowRatio` for OpenStudio versions before 2.7.0
- `SizingSystem.setSizingOption`
- `openstudio.convert`


## Code Pattern

1. Load `current_model_path` and find `created_objects.air_loop`.
2. Convert all design temperatures from F to C using `openstudio.convert`.
3. Set standard VAV values:
   - type of load to size on: `Sensible`;
   - preheat, precool, central cooling, and central heating design temperatures;
   - preheat and precool humidity ratio: `0.008`;
   - central cooling humidity ratio: `0.0085`;
   - central heating humidity ratio: `0.0080`;
   - system outdoor-air method: `ZoneSum`;
   - design airflow methods: `DesignDay`;
   - all-outdoor-air cooling/heating: `False`.
   
4. Set minimum system airflow ratio with the OpenStudio-version-compatible setter.
5. Set sizing option, usually `Coincident`.
6. Save and return converted values in state.


## Missing Field Behavior

Return missing fields if the air loop name, model paths, minimum airflow ratio,
or sizing option are absent.

If `openstudio_version` is absent, the script may discover it and include it in
the state patch.

## State Patch

Return only changed fields:

```json
{
  "ok": true,
  "state_patch": {
    "current_model_path": "/path/to/output.osm",
    "openstudio_version": "3.8.0",
    "completed_steps": [
      "sizing_system"
    ],
    "pending_steps_remove": [
      "sizing_system"
    ],
    "design_temperatures": {
      "converted_to_si": true
    },
    "sizing": {
      "minimum_system_airflow_ratio": 0.3,
      "sizing_option": "Coincident"
    },
    "created_objects": {
      "sizing_system": "3 Zone VAV Sizing System"
    },
    "warnings": []
  }
}
```

## Validation Checks

- The target air loop has one sizing system.
- Temperature values were converted to SI before SDK setters.
- Version-specific airflow-ratio setter was selected intentionally.


