---
name: sdk_hvac
description: OpenStudio Python SDK examples for HVAC topology inspection and scoped HVAC object edits.
version: 0.1.0
---

# SDK HVAC Context

Use this pack for air loops, thermal-zone equipment, coils, fans, thermostats,
setpoint managers, sizing objects, outdoor air controllers, and HVAC topology
inspection. Do not use this pack to run simulations; use MCP `sim_*` tools for
simulation execution.

For HVAC object creation, apply the global object creation rule from
`sdk_core_patterns`: inspect the constructor and setter calls, identify every
required numeric value, unit, schedule, node, thermal zone, and component object,
then ask the user for missing inputs before execution. If a setter requires
another OpenStudio object, retrieve candidate objects from the model and ask the
user to choose. If the user approves defaults, list them with
`Object:Name.parameter: assumed to be x`.

## Inspect Air Loop Topology

```python
air_loop_rows = []
air_loop_getter = getattr(model, "getAirLoopHVACs", None)
air_loops = list(air_loop_getter()) if callable(air_loop_getter) else []
if not callable(air_loop_getter):
    warnings.append("This SDK does not expose model.getAirLoopHVACs().")

for air_loop in air_loops:
    served_zones = [zone.nameString() for zone in air_loop.thermalZones()]
    supply_components = []
    for comp in air_loop.supplyComponents():
        name = comp.nameString() if hasattr(comp, "nameString") else str(comp)
        supply_components.append({
            "name": name,
            "python_type": type(comp).__name__,
        })
    air_loop_rows.append({
        "air_loop": air_loop.nameString(),
        "served_zones": served_zones,
        "supply_components": supply_components,
    })
```

Use this for high-level HVAC topology summaries before drilling into specific
component types.

## Inspect Zone Thermostats

```python
thermostat_rows = []
for zone in model.getThermalZones():
    thermostat_getter = getattr(zone, "thermostatSetpointDualSetpoint", None)
    if not callable(thermostat_getter):
        thermostat_rows.append({
            "thermal_zone": zone.nameString(),
            "thermostat": None,
            "warning": "thermostatSetpointDualSetpoint getter is unavailable",
        })
        continue

    thermostat_opt = thermostat_getter()
    if not thermostat_opt.is_initialized():
        thermostat_rows.append({
            "thermal_zone": zone.nameString(),
            "thermostat": None,
        })
        continue

    thermostat = thermostat_opt.get()
    heat_opt = thermostat.heatingSetpointTemperatureSchedule()
    cool_opt = thermostat.coolingSetpointTemperatureSchedule()
    thermostat_rows.append({
        "thermal_zone": zone.nameString(),
        "thermostat": thermostat.nameString(),
        "heating_schedule": heat_opt.get().nameString() if heat_opt.is_initialized() else None,
        "cooling_schedule": cool_opt.get().nameString() if cool_opt.is_initialized() else None,
    })
```

Thermostat schedule accessors return optionals.

## Create Single-Zone Air Loop Skeleton

Before using this creation pattern, ask for the air-loop name, target thermal
zone, terminal name if needed, and availability schedule preference if any are
missing. If the user says to keep defaults, document the chosen thermal zone and
schedule assumptions.

```python
air_loop = openstudio.model.AirLoopHVAC(model)
air_loop.setNightCycleControlType("CycleOnAny")

always_on = model.alwaysOnDiscreteSchedule()
terminal = openstudio.model.AirTerminalSingleDuctConstantVolumeNoReheat(
    model,
    always_on,
)
air_loop.addBranchForZone(thermal_zone, terminal)
```

This creates an air loop and connects it to one thermal zone using a
constant-volume no-reheat terminal.

## Outdoor Air Controller and System

Before using this creation pattern, ask for controller name, minimum outdoor air
schedule, economizer control type, maximum dry bulb temperature with units,
lockout type, and target air loop. `setMinimumOutdoorAirSchedule` requires an
OpenStudio schedule object; list candidate schedules from the model and ask the
user to select one when it is not specified. Convert temperature to SI Celsius
before calling `setEconomizerMaximumLimitDryBulbTemperature`.

```python
controller_oa = openstudio.model.ControllerOutdoorAir(model)
controller_oa.setMinimumOutdoorAirSchedule(hvac_schedule)
controller_oa.setEconomizerControlType("FixedDryBulb")
controller_oa.setEconomizerMaximumLimitDryBulbTemperature(max_temp_c)
controller_oa.setLockoutType("LockoutWithHeating")
controller_oa.setEconomizerMinimumLimitDryBulbTemperature(0)

controller_mv = controller_oa.controllerMechanicalVentilation()
controller_mv.setAvailabilitySchedule(hvac_schedule)

oa_system = openstudio.model.AirLoopHVACOutdoorAirSystem(model, controller_oa)
oa_system.addToNode(air_loop.supplyOutletNode())
```

This creates an outdoor air system and attaches it to the air loop supply outlet
node.

## DX Cooling Coil with Curves

Before creating a DX coil, ask for coil name, availability schedule, rated COP,
and curve choices or permission to use defaults. If defaults are approved,
document every curve and rated-COP assumption.

```python
cap_ft = openstudio.model.CurveBiquadratic(model)
cap_flow = openstudio.model.CurveQuadratic(model)
eir_ft = openstudio.model.CurveBiquadratic(model)
eir_flow = openstudio.model.CurveQuadratic(model)
plf = openstudio.model.CurveQuadratic(model)

cooling_coil = openstudio.model.CoilCoolingDXSingleSpeed(
    model,
    availability_schedule,
    cap_ft,
    cap_flow,
    eir_ft,
    eir_flow,
    plf,
)
cooling_coil.autosizeRatedTotalCoolingCapacity()
cooling_coil.setRatedCOP(4.4)
```

Reviewed code configures the curve coefficients before constructing the coil.
When inspecting existing models, report curve names and rated COP rather than
rewriting curves unless the user asks for an edit.

## Gas Heating Coil and Constant Volume Fan

Before creating these objects, ask for names, availability schedules,
efficiencies, and fan pressure rise. `setPressureRise` expects Pascals. If the
user provides IP pressure units, convert before setting.

```python
heating_coil = openstudio.model.CoilHeatingGas(model, availability_schedule)
heating_coil.autosizeNominalCapacity()
heating_coil.setGasBurnerEfficiency(0.8)

fan = openstudio.model.FanConstantVolume(model, hvac_schedule)
fan.autosizeMaximumFlowRate()
fan.setFanEfficiency(0.65)
fan.setMotorEfficiency(0.90)
fan.setPressureRise(373.6)
```

These create autosized heating and fan components with explicit efficiencies
and pressure rise.

## Add Components to Air Loop Nodes

```python
supply_outlet = air_loop.supplyOutletNode()
cooling_coil.addToNode(supply_outlet)
heating_coil.addToNode(supply_outlet)
fan.addToNode(supply_outlet)

fan_inlet = fan.inletModelObject().get().to_Node().get()
fan_outlet = fan.outletModelObject().get().to_Node().get()
cooling_outlet = cooling_coil.outletModelObject().get().to_Node().get()
```

Node accessors are optional in the reviewed code and are unwrapped after
components have been added to the loop. For generated scripts, check optionals
unless the setup was created in the same script.

## Setpoint Managers and Thermostat

Before creating setpoint managers or thermostats, ask for target nodes, control
zone, heating schedule, cooling schedule, maximum/minimum supply temperatures,
and units. Retrieve candidate thermal zones and schedules from the model for
user selection when they are not specified.

```python
mixed_air = openstudio.model.SetpointManagerMixedAir(model)
mixed_air.setFanInletNode(fan_inlet)
mixed_air.setFanOutletNode(fan_outlet)
mixed_air.setReferenceSetpointNode(fan_outlet)
mixed_air.setControlVariable("Temperature")
mixed_air.addToNode(cooling_outlet)

single_zone = openstudio.model.SetpointManagerSingleZoneReheat(model)
single_zone.setControlZone(thermal_zone)
single_zone.setMaximumSupplyAirTemperature(99)
single_zone.setMinimumSupplyAirTemperature(-99)
single_zone.addToNode(supply_outlet)

thermostat = openstudio.model.ThermostatSetpointDualSetpoint(model)
thermostat.setCoolingSetpointTemperatureSchedule(cooling_schedule)
thermostat.setHeatingSetpointTemperatureSchedule(heating_schedule)
thermal_zone.setThermostatSetpointDualSetpoint(thermostat)
```

Use these patterns for topology explanation or carefully scoped HVAC edits.
Changing HVAC behavior generally requires a validation and simulation workflow
through MCP after the model edit.

## Sizing Parameters

```python
cooling_supply_c = openstudio.convert(55, "F", "C").get()
heating_supply_c = openstudio.convert(90, "F", "C").get()

sizing_system = air_loop.sizingSystem()
sizing_system.setCentralHeatingMaximumSystemAirFlowRatio(1)
sizing_system.setCentralCoolingDesignSupplyAirTemperature(cooling_supply_c)
sizing_system.setCentralHeatingDesignSupplyAirTemperature(heating_supply_c)
sizing_system.setAllOutdoorAirinCooling(False)
sizing_system.setAllOutdoorAirinHeating(False)

sizing_zone = thermal_zone.sizingZone()
sizing_zone.setCoolingDesignAirFlowMethod("DesignDayWithLimit")
sizing_zone.setCoolingMinimumAirFlow(0.00141573)
sizing_zone.setZoneCoolingDesignSupplyAirTemperature(cooling_supply_c)
sizing_zone.setZoneHeatingDesignSupplyAirTemperature(heating_supply_c)
```

OpenStudio unit conversion returns an optional. Check `is_initialized()` before
`.get()` when the value or unit strings are generated dynamically.
