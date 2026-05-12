---
name: sdk_daylighting
description: OpenStudio Python SDK examples for adding daylighting controls to spaces.
version: 0.1.0
---

# SDK Daylighting Context

Use this pack for daylighting sensor creation and space-level daylighting
control edits. This is a good candidate for `run_python` because it is a scoped
model edit that does not require simulation.

For daylighting-control creation, apply the global object creation rule from
`sdk_core_patterns`: ask for target spaces, sensor names, illuminance setpoints,
position rules, controlled-zone fractions, and default assumptions before
execution.

## Sensor Point at Center of Floor

```python
def point_at_center_of_floor(space, z_offset_m=1.0):
    floor_points = []
    for surface in space.surfaces():
        if surface.surfaceType() != "Floor":
            continue
        for vertex in surface.vertices():
            floor_points.append(vertex)
    if not floor_points:
        return None

    x = sum(point.x() for point in floor_points) / len(floor_points)
    y = sum(point.y() for point in floor_points) / len(floor_points)
    z = min(point.z() for point in floor_points) + z_offset_m
    return openstudio.Point3d(x, y, z)
```

## Add Daylighting Control to Selected Spaces

```python
target_space_names = {"Core_ZN Space", "Perimeter_ZN_1 Space"}
for space in model.getSpaces():
    if space.nameString() not in target_space_names:
        continue

    position = point_at_center_of_floor(space, z_offset_m=1.0)
    if position is None:
        warnings.append(f"No floor vertices found for {space.nameString()}; skipped daylighting control.")
        continue

    sensor = openstudio.model.DaylightingControl(model)
    sensor.setSpace(space)
    sensor.setName(f"{space.nameString()} Daylight Sensor")
    sensor.setPosition(position)
    sensor.setPhiRotationAroundZAxis(0.0)
    sensor.setIlluminanceSetpoint(430.0)
    sensor.setLightingControlType("Continuous")
    sensor.setMinimumInputPowerFractionforContinuousDimmingControl(0.3)
    sensor.setMinimumLightOutputFractionforContinuousDimmingControl(0.2)
    sensor.setNumberofSteppedControlSteps(1)
    sensor.setProbabilityLightingwillbeResetWhenNeededinManualSteppedControl(0)
    sensor.setNumberofDaylightingViews(1)
    sensor.setMaximumAllowableDiscomfortGlareIndex(1)
    changes.append({
        "object": sensor.nameString(),
        "field": "daylighting_control",
        "space": space.nameString(),
        "illuminance_setpoint_lux": 430.0,
    })
```

## Assign Daylighting Control to Thermal Zone

```python
zone_opt = space.thermalZone()
if not zone_opt.is_initialized():
    warnings.append(f"{space.nameString()} has no thermal zone; skipped daylighting control.")
else:
    zone = zone_opt.get()
    if (
        not zone.primaryDaylightingControl().empty()
        and zone.secondaryDaylightingControl().empty()
    ):
        existing_primary = zone.primaryDaylightingControl().get()
        zone.setSecondaryDaylightingControl(existing_primary)
        zone.setFractionofZoneControlledbySecondaryDaylightingControl(
            zone.fractionofZoneControlledbyPrimaryDaylightingControl()
        )
    zone.setPrimaryDaylightingControl(sensor)
    zone.setFractionofZoneControlledbyPrimaryDaylightingControl(0.5)
```

When replacing an existing primary daylighting control, preserve it as secondary
when the secondary slot is available.

## Keep Primary and Secondary Fractions Within 1.0

```python
primary = zone.fractionofZoneControlledbyPrimaryDaylightingControl()
secondary = zone.fractionofZoneControlledbySecondaryDaylightingControl()
if primary + secondary > 1.0:
    primary = round(primary, 6)
    zone.setFractionofZoneControlledbyPrimaryDaylightingControl(primary)
    zone.setFractionofZoneControlledbySecondaryDaylightingControl(1.0 - primary)
```

Reviewed source code rounds daylighting fractions to avoid EnergyPlus errors
from OpenStudio string-conversion precision differences.

## Avoid Duplicate Sensors

```python
existing_spaces = set()
for control in model.getDaylightingControls():
    space_opt = control.space()
    if space_opt.is_initialized():
        existing_spaces.add(space_opt.get().nameString())

if space.nameString() in existing_spaces:
    warnings.append(f"{space.nameString()} already has a daylighting control; skipped.")
```

Confirm the target spaces and illuminance setpoint with the user before
execution. Daylighting impact still requires MCP simulation and `results_*`
queries after the model edit is complete.
