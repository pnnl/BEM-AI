---
name: openstudio_hvac_ptac_zone_equipment_creator
description: Create a packaged terminal air conditioner (PTAC) zone equipment with configurable heating, cooling, and DOAS integration.
version: 0.1.0
output_format: markdown_with_json_state_patch
---

## Scope

Use this child skill to create a `ZoneHVACPackagedTerminalAirConditioner` for a
target thermal zone. It handles heating coil type selection (gas furnace, boiler,
air-to-water heat pump, or none), DX cooling coil setup, fan operating mode
configuration based on DOAS pairing, night cycling, and zone equipment
prioritization.

Do not create air loops, plant loops, outdoor-air systems, schedules (beyond
applying existing ones), or simulations in this skill.

## Required State Fields

- `current_model_path`
- `output_model_path`
- `ptac.target_zone_name`
- `ptac.fan_schedule_name`
- `ptac.cooling_cop`
- `ptac.heating_type` one of: `'Furnace'`, `'Boiler'`, `'District Heating'`, `'AWHP'`, or `'None'`
- `ptac.has_doas` boolean
- `ptac.fan_operating_mode` one of: `'cycling'` or `'continuous'`
- `completed_steps`
- `pending_steps`

Conditional required fields:

- `ptac.heating_fuel` when `heating_type` is `'Furnace'` (one of: `'NaturalGas'`, `'PropaneGas'`, `'Oil'`, `'Electricity'`)
- `ptac.heating_efficiency` when heating is enabled; if absent or 0, defaults are applied (0.78 AFUE for combustion, 1.0 for electric, COP for heat pump)
- `ptac.heating_plant_loop_name` when `heating_type` is `'Boiler'`, `'District Heating'`, or `'AWHP'`

## Optional State Fields

- `ptac.ptac_name` (defaults to `{zone_name} PTAC`)
- `ptac.heating_fuel` when `heating_type` is `'Furnace'` (else not applicable)
- `warnings`

## SDK Methods To Verify

- `Model.getThermalZones`
- `ThermalZone.nameString`
- `FanOnOff.new`
- `CoilHeatingGas.new`
- `CoilHeatingElectric.new`
- `CoilHeatingWater.new`
- `CoilCoolingDXSingleSpeed.new`
- `ZoneHVACPackagedTerminalAirConditioner.new`
- `ZoneHVACPackagedTerminalAirConditioner.setSupplyAirFanOperatingModeSchedule`
- `ZoneHVACPackagedTerminalAirConditioner.setOutdoorAirFlowRateDuringCoolingOperation`
- `ZoneHVACPackagedTerminalAirConditioner.setOutdoorAirFlowRateDuringHeatingOperation`
- `ZoneHVACPackagedTerminalAirConditioner.setOutdoorAirFlowRateWhenNoCoolingorHeatingisNeeded`
- `ZoneHVACPackagedTerminalAirConditioner.addToThermalZone`
- `AvailabilityManagerNightCycle.new`
- `PlantLoop.addDemandBranchForComponent`
- `ThermalZone.setHeatingPriority`
- `ThermalZone.setCoolingPriority`
- `Model.alwaysOnDiscreteSchedule`
- `Model.alwaysOffDiscreteSchedule`
- `AvailabilityManagerNightCycle.setControlType`
- `AvailabilityManagerNightCycle.setCyclingRunTimeControlType`
- `AvailabilityManagerNightCycle.setApplicabilitySchedule`
- `AvailabilityManagerNightCycle.setThermostatTolerance`
- `AvailabilityManagerNightCycle.setControlThermalZones`
- `CurveBiquadratic.new`
- `CurveQuadratic.new`

## PTAC DX Cooling Coil Performance Curves

Five curves are created and passed to `CoilCoolingDXSingleSpeed.new`. If a curve with the same name
already exists in the model it is reused rather than duplicated.

| Role | OS Class | Model name |
|------|----------|------------|
| Cap-FT | `CurveBiquadratic` | `PTAC Cooling Coil Cap-FT` |
| Cap-FF | `CurveQuadratic` | `PTAC Cooling Coil Cap-FF` |
| EIR-FT | `CurveBiquadratic` | `PTAC Cooling Coil EIR-FT` |
| EIR-FF | `CurveQuadratic` | `PTAC Cooling Coil EIR-FF` |
| PLF-FPLR | `CurveQuadratic` | `PTAC Cooling Coil PLF-FPLR` |

### Cap-FT — Cooling Capacity as Function of Temperature (`CurveBiquadratic`)

x = entering wet-bulb temperature (°C), y = outdoor dry-bulb temperature (°C)

| Coefficient | Value |
|-------------|-------|
| C1 constant | 0.942587793 |
| C2 x | 0.009543347 |
| C3 x² | 0.00068377 |
| C4 y | -0.011042676 |
| C5 y² | 0.000005249 |
| C6 x·y | -0.00000972 |
| x min / max | 12.77778 / 23.88889 |
| y min / max | 23.88889 / 46.11111 |

### Cap-FF — Cooling Capacity as Function of Flow Fraction (`CurveQuadratic`)

x = air flow fraction

| Coefficient | Value |
|-------------|-------|
| C1 constant | 0.8 |
| C2 x | 0.2 |
| C3 x² | 0.0 |
| x min / max | 0.5 / 1.5 |

### EIR-FT — Energy Input Ratio as Function of Temperature (`CurveBiquadratic`)

x = entering wet-bulb temperature (°C), y = outdoor dry-bulb temperature (°C)

| Coefficient | Value |
|-------------|-------|
| C1 constant | 0.342414409 |
| C2 x | 0.034885008 |
| C3 x² | -0.0006237 |
| C4 y | 0.004977216 |
| C5 y² | 0.000437951 |
| C6 x·y | -0.000728028 |
| x min / max | 12.77778 / 23.88889 |
| y min / max | 23.88889 / 46.11111 |

### EIR-FF — Energy Input Ratio as Function of Flow Fraction (`CurveQuadratic`)

x = air flow fraction

| Coefficient | Value |
|-------------|-------|
| C1 constant | 1.1552 |
| C2 x | -0.1808 |
| C3 x² | 0.0256 |
| x min / max | 0.5 / 1.5 |

### PLF-FPLR — Part Load Fraction as Function of Part Load Ratio (`CurveQuadratic`)

x = part load ratio

| Coefficient | Value |
|-------------|-------|
| C1 constant | 0.85 |
| C2 x | 0.15 |
| C3 x² | 0.0 |
| x min / max | 0.0 / 1.0 |

## Night Cycling and Availability Manager Logic

### Decision rule

Night cycling is applied unless both conditions are true: `fan_operating_mode == 'cycling'` **and**
`has_doas`. In that case the DOAS governs ventilation and the zone unit should not independently
night-cycle. In all other combinations — continuous fan, or cycling without a DOAS — night cycling
is applied.

### Fan schedule wiring

The fan is always a `FanOnOff`. The schedule passed to the constructor and the schedule set via
`setSupplyAirFanOperatingModeSchedule` differ depending on the operating mode:

| Condition | Fan constructor schedule | `setSupplyAirFanOperatingModeSchedule` |
|-----------|--------------------------|----------------------------------------|
| cycling + has_doas | always-on schedule | always-off schedule |
| all other cases | `ptac.fan_schedule_name` | always-on schedule |

The always-off supply-fan-mode schedule is what causes the fan to cycle with thermostat calls rather
than run continuously.

### `AvailabilityManagerNightCycle` settings (when night cycling applies)

Create one `AvailabilityManagerNightCycle` and configure it as follows:

- **Control type**: `CycleOnControlZone`
- **Cycling run time control type**: `ThermostatWithMinimumRunTime`
- **Applicability schedule**: always-on schedule
- **Thermostat tolerance**: 0.2°C
- **Control thermal zones**: set to the single target zone via `setControlThermalZones`

## Code Pattern

1. Load `current_model_path` and find the target zone by `ptac.target_zone_name`.
2. Retrieve the fan schedule and outdoor-air availability schedule from the model
   by `ptac.fan_schedule_name`. If not found, ask the user.
3. Create `FanOnOff` with the fan schedule.
4. **Select and create heating coil** based on `ptac.heating_type`:
   - If `'Furnace'`: Create `CoilHeatingGas` with fuel recorded in object name;
     apply default 0.78 AFUE if efficiency not provided.
   - If `'Boiler'` or `'District Heating'` or `'AWHP'`: Create `CoilHeatingWater`,
     find `ptac.heating_plant_loop_name`, and add the coil to the demand branch.
     Apply default COP (4.0 for AWHP, 0.9 for others) if efficiency not provided.
   - If `'None'`: Create `CoilHeatingElectric` with always-off schedule.
5. Create `CoilCoolingDXSingleSpeed` with `ptac.cooling_cop` and PTAC-specific
   performance curves (distinct from PTHP). Auto-size rated total cooling capacity.
6. **Determine fan operating mode schedule** from the decision matrix:
   - Cycling + DOAS: always-off schedule (fan cycles with thermostat call)
   - All other cases: always-on schedule (fan runs continuously)
7. Create `ZoneHVACPackagedTerminalAirConditioner` with fan, heating, cooling coils.
8. Set fan operating mode schedule via `setSupplyAirFanOperatingModeSchedule`.
9. **Apply DOAS outdoor air zeroing** if `ptac.has_doas`:
   - Set all three outdoor air flow rate methods to 0.0.
10. **Apply night cycling** — skip only when `fan_operating_mode == 'cycling'` AND `has_doas`;
    apply in all other cases:
    - Create `AvailabilityManagerNightCycle`.
    - Set control type to `CycleOnControlZone`.
    - Set cycling run time control type to `ThermostatWithMinimumRunTime`.
    - Set applicability schedule to always-on schedule.
    - Wire the fan schedule via `setString(3, fan_schedule_name)`.
    - Set thermostat tolerance to 0.2°C.
    - Set control thermal zones to the single target zone.
11. Set heating and cooling priority to 1 for the PTAC on the zone.
12. Add PTAC to the target zone.
13. Save the model and return created PTAC object name and configuration summary.

## Missing Field Behavior

Return missing fields for absent required state. If the fan schedule, outdoor-air
schedule, target zone, or plant loop (for water coils) cannot be found, ask the
user to select from candidates in the model or provide a name. Do not create
schedules or plant loops in this skill.

## State Patch

```json
{
  "ok": true,
  "state_patch": {
    "current_model_path": "/path/to/output.osm",
    "completed_steps": ["ptac_zone_equipment"],
    "pending_steps_remove": ["ptac_zone_equipment"],
    "ptac": {
      "ptac_name": "Guest Room 101 PTAC",
      "target_zone_name": "Guest Room 101",
      "heating_type": "Furnace",
      "heating_fuel": "NaturalGas",
      "heating_efficiency": 0.78,
      "cooling_cop": 3.4,
      "has_doas": false,
      "fan_operating_mode": "continuous"
    },
    "created_objects": {
      "ptac": "Guest Room 101 PTAC",
      "heating_coil": "Guest Room 101 Furnace Htg Coil",
      "cooling_coil": "Guest Room 101 DX Clg Coil",
      "fan": "Guest Room 101 Fan",
      "night_cycle_manager": "Guest Room 101 Night Cycle"
    },
    "warnings": []
  }
}
```

## Validation Checks

- PTAC exists with expected name and is connected to the target zone.
- Heating coil type matches the configuration: `CoilHeatingGas` for furnace,
  `CoilHeatingWater` for plant-based, `CoilHeatingElectric` (always-off) for none.
- Cooling coil is a DX single-speed with rated COP set from input.
- Fan operates on the correct schedule (always-off for cycling+DOAS, always-on
  otherwise).
- If `has_doas`, all three outdoor air flow rates are zeroed.
- Night cycling is applied except in cycling+DOAS combination.
- Zone heating and cooling priorities are set to 1.
