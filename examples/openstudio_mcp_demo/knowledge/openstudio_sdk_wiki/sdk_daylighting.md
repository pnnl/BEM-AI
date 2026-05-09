---
name: sdk_daylighting
description: OpenStudio Python SDK examples for adding daylighting controls to spaces.
version: 0.1.0
source_domains:
  - openstudio-standards/daylighting/space.rb
  - openstudio-standards/geometry/create.rb
---

# SDK Daylighting Context

Use this pack for daylighting sensor creation and space-level daylighting
control edits. This is a good candidate for `run_python` because it is a scoped
model edit that does not require simulation.

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
    changes.append({
        "object": sensor.nameString(),
        "field": "daylighting_control",
        "space": space.nameString(),
        "illuminance_setpoint_lux": 430.0,
    })
```

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
