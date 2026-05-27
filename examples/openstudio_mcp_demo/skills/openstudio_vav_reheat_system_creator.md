---
name: openstudio_vav_reheat_system_creator
description: Draft bounded OpenStudio Python SDK scripts that add a multi-zone VAV reheat air system.
version: 0.1.0
output_format: markdown_with_json_summary
---

## Scope

Use this skill when the user asks to add, create, prototype, or draft a
multi-zone variable air volume system with terminal reheat in an OpenStudio
model.

This skill is for script drafting and model editing through `run_python`. Do not
use it to run simulations, poll simulations, or retrieve results. After the
edited model is saved, route validation, sizing, simulation, and result
workflows to MCP `model_*`, `sim_*`, and `results_*` tools.

## Required Companion Context

Before drafting a VAV reheat script, load:

- `openstudio_sdk_model_editor`
- `sdk_index`
- `sdk_core_patterns`
- `sdk_hvac`
- `sdk_schedules`
- `sdk_spaces_zones_loads`

Then use `sdk_docs_get_method` or targeted Python binding introspection for the
OpenStudio classes and methods that the generated script will call. At minimum,
verify constructors or setters for:

- `AirLoopHVAC`
- `SizingSystem`
- `ScheduleRuleset` or another temperature schedule class
- `SetpointManagerScheduled`
- `FanVariableVolume`
- `CoilHeatingWater`, `CoilHeatingGas`, or `CoilHeatingElectric`
- `CoilCoolingWater` or the selected DX cooling coil class
- `ControllerOutdoorAir`
- `AirLoopHVACOutdoorAirSystem`
- `AirTerminalSingleDuctVAVReheat` or `AirTerminalSingleDuctVAVNoReheat`
- `ThermalZone.sizingZone`

If local SDK docs are unavailable, say so and verify uncertain Python binding
method names with read-only introspection before drafting the final script.

## Inputs To Confirm

Do not draft or execute a VAV creation script until these are known or the user
explicitly approves defaults:

- input model path and output model path;
- system name;
- target thermal zones, either explicit names or all conditioned zones;
- reheat type: `Water`, `NaturalGas`, `Electricity`, or `None`;
- central heating coil type: existing hot-water loop, gas, electric, or none;
- central cooling coil type: existing chilled-water loop or DX fallback;
- HVAC operation schedule, or approval to use Always On Discrete;
- outdoor-air damper schedule, or approval to leave unset;
- fan total efficiency, motor efficiency, and pressure rise with units;
- minimum system airflow ratio;
- sizing option, commonly `Coincident`;
- economizer control type, or approval to leave default;
- whether to assign a return plenum.

For water coils, confirm the target plant loop by name. Do not silently create a
hot-water or chilled-water plant loop inside this skill unless the user asked
for loop creation and supplied loop design inputs. If a required plant loop is
missing, ask whether to use gas/electric/DX fallback equipment or to create the
plant loop as a separate scoped task.

All numeric SDK setter inputs should be SI. If the user supplies IP units,
convert before calling SDK setters and report the conversion.

If defaults are approved, list assumptions using this exact format:

```text
Object:Name.parameter: assumed to be x
```

## Standards-Derived Execution Logic

The VAV reheat creation sequence is:

1. Create an `AirLoopHVAC`.
2. Resolve HVAC operation and outdoor-air damper schedules.
3. Build standard design temperature values:
   - preheat supply air: 45 F
   - precool supply air: 55 F
   - central heating supply air: 55 F
   - central cooling supply air: 55 F
   - zone heating supply air: 104 F
   - zone cooling supply air: 55 F
   Convert each value to Celsius through `openstudio.convert`.
4. Configure the air-loop `SizingSystem`:
   - type of load to size on: `Sensible`
   - autosize design outdoor air flow rate
   - preheat, precool, central cooling, and central heating design temperatures
   - preheat and precool humidity ratio: `0.008`
   - central cooling humidity ratio: `0.0085`
   - central heating humidity ratio: `0.0080`
   - central heating maximum system airflow ratio or legacy minimum system
     airflow ratio depending on SDK availability
   - sizing option, usually `Coincident`
   - all-outdoor-air cooling/heating: `False`
   - system outdoor-air method: `ZoneSum`
   - cooling and heating design airflow methods: `DesignDay`
5. Create a constant supply-air temperature schedule and attach a
   `SetpointManagerScheduled` to the air-loop supply outlet node.
6. Create a variable-volume fan:
   - name it from the air-loop name;
   - set fan efficiency;
   - set motor efficiency;
   - convert pressure rise to Pa if supplied in `inH2O`;
   - set end-use subcategory to `VAV System Fans` when supported;
   - add the fan to the air-loop supply inlet node.
7. Create a central heating coil:
   - if a hot-water loop is supplied, create `CoilHeatingWater`, add it to the
     loop demand side, add it to the air-loop supply inlet node, and set rated
     water/air temperatures;
   - otherwise create a gas or electric heating coil based on user input.
8. Create a central cooling coil:
   - if a chilled-water loop is supplied, create `CoilCoolingWater`, add it to
     the loop demand side, and add it to the air-loop supply inlet node;
   - otherwise use the explicitly approved DX fallback class and default curves
     or ask for curve inputs.
9. Create the outdoor-air controller/system:
   - `ControllerOutdoorAir`
   - name it from the air-loop name;
   - set minimum limit type to `FixedMinimum`;
   - autosize minimum outdoor airflow;
   - reset maximum outdoor-air fraction schedule;
   - reset economizer minimum dry-bulb temperature;
   - set economizer control type only when provided;
   - set minimum outdoor-air schedule only when an OA damper schedule is
     provided;
   - get `controllerMechanicalVentilation`, name it, and set system outdoor-air
     method to `ZoneSum`;
   - create `AirLoopHVACOutdoorAirSystem` and add it to the air-loop supply
     inlet node.
10. Set the air-loop availability schedule and night cycle control:
    - availability schedule from the resolved HVAC operation schedule;
    - night cycle control type: `CycleOnAny`;
    - if a night-cycle availability manager is exposed, set cycling runtime to
      `1800` seconds.
11. For each target thermal zone:
    - create a reheat coil based on the reheat type;
    - create `AirTerminalSingleDuctVAVReheat` when there is a reheat coil, or
      `AirTerminalSingleDuctVAVNoReheat` when there is no reheat;
    - set terminal name from the zone name;
    - set zone minimum airflow method/input method to `Constant`, using the
      SDK-supported method name;
    - for reheat terminals, set damper heating action to `Normal` and maximum
      reheat air temperature to the zone heating supply temperature;
    - set constant minimum airflow fraction to `0.3` unless the user supplied a
      different strategy;
    - add the terminal branch to the zone;
    - configure zone sizing:
      - cooling design airflow method: `DesignDayWithLimit`
      - heating design airflow method: `DesignDay` for reheat systems
      - heating maximum airflow fraction: `1.0`
      - zone cooling design supply air temperature
      - zone heating design supply air temperature for reheat systems
    - assign return plenum only when explicitly supplied.
12. Save to a copied output `.osm`, validate object counts, and report created
    object names.

## Python Drafting Pattern

Generated scripts should define small helpers instead of writing one long
procedure. Use names like:

```python
def convert_or_raise(value, from_unit, to_unit): ...
def get_schedule_by_name(model, name): ...
def create_constant_temperature_schedule(model, name, value_c): ...
def resolve_plant_loop(model, loop_name): ...
def select_target_zones(model, zone_names): ...
def configure_vav_sizing_system(air_loop, design_temps, min_ratio, sizing_option): ...
def create_vav_supply_fan(model, air_loop, fan_efficiency, motor_efficiency, pressure_rise_pa): ...
def create_central_heating_coil(...): ...
def create_central_cooling_coil(...): ...
def create_outdoor_air_system(...): ...
def add_vav_terminal_for_zone(...): ...
```

The final script must print the standard JSON result contract from
`openstudio_sdk_model_editor`, including:

- created air-loop name;
- target zone names;
- created fan, coil, outdoor-air-system, terminal, and setpoint-manager names;
- plant loops used;
- assumptions;
- warnings;
- output model path.

## Required Clarification Behavior

Ask a clarifying question instead of drafting code when:

- target zones are ambiguous;
- the user requests water coils but no hot-water or chilled-water loop name is
  supplied;
- the user gives a numeric fan pressure rise without units;
- the user asks for DX cooling but does not approve default DX curves;
- schedule names are missing and the user has not approved Always On defaults;
- the model may already contain an air loop with the requested name;
- the requested edit would overwrite the input model.

## Post-Edit Recommendation

After creating and saving the edited model, recommend:

1. `model_load` for the copied `.osm`;
2. `model_validate`;
3. a sizing run through `sim_run`;
4. `results_query` with `sizing_summary`;
5. review of warnings and autosized flow/capacity outputs before annual
   simulation.
