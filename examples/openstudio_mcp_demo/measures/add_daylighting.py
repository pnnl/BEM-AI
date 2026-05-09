from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import openstudio


def _has_exterior_fenestration(space: openstudio.model.Space) -> bool:
    for surface in space.surfaces():
        if surface.outsideBoundaryCondition() != "Outdoors":
            continue
        if len(surface.subSurfaces()) > 0:
            return True
    return False


def _center_floor_point(space: openstudio.model.Space, sensor_height_m: float) -> openstudio.Point3d | None:
    floors = [surface for surface in space.surfaces() if surface.surfaceType() == "Floor"]
    if not floors:
        return None

    bbox = openstudio.BoundingBox()
    for floor in floors:
        bbox.addPoints(floor.vertices())

    min_x = bbox.minX()
    max_x = bbox.maxX()
    min_y = bbox.minY()
    max_y = bbox.maxY()
    min_z = bbox.minZ()
    if not (min_x.is_initialized() and max_x.is_initialized() and min_y.is_initialized() and max_y.is_initialized() and min_z.is_initialized()):
        return None

    x_pos = (min_x.get() + max_x.get()) / 2.0
    y_pos = (min_y.get() + max_y.get()) / 2.0
    z_pos = min_z.get() + sensor_height_m
    return openstudio.Point3d(x_pos, y_pos, z_pos)


def main() -> int:
    input_path_raw = os.getenv("OSM_INPUT_PATH", "").strip()
    output_path_raw = os.getenv("OSM_OUTPUT_PATH", "").strip()
    args_raw = os.getenv("MEASURE_ARGS_JSON", "{}")

    if not input_path_raw or not output_path_raw:
        print(json.dumps({"ok": False, "error": "OSM_INPUT_PATH and OSM_OUTPUT_PATH are required."}))
        return 2

    input_path = Path(input_path_raw).resolve()
    output_path = Path(output_path_raw).resolve()
    if not input_path.exists():
        print(json.dumps({"ok": False, "error": f"Input model not found: {input_path}"}))
        return 2

    try:
        args = json.loads(args_raw)
    except json.JSONDecodeError:
        args = {}

    sensor_height_m = float(args.get("sensor_height_m", 1.0))
    phi_rotation_around_z_axis = float(args.get("phi_rotation_around_z_axis", 0.0))
    illuminance_setpoint = float(args.get("illuminance_setpoint", 430.0))
    lighting_control_type = str(args.get("lighting_control_type", "Continuous"))
    minimum_input_power_fraction_continuous = float(args.get("minimum_input_power_fraction_continuous", 0.3))
    minimum_light_output_fraction_continuous = float(args.get("minimum_light_output_fraction_continuous", 0.2))
    number_of_stepped_control_steps = int(args.get("number_of_stepped_control_steps", 1))

    translator = openstudio.openstudioosversion.VersionTranslator()
    loaded = translator.loadModel(str(input_path))
    if not loaded.is_initialized():
        print(json.dumps({"ok": False, "error": f"Failed to load model: {input_path}"}))
        return 2
    model = loaded.get()

    spaces_touched: list[str] = []
    warnings: list[str] = []
    sensors_added = 0

    for space in model.getSpaces():
        if not _has_exterior_fenestration(space):
            continue
        point = _center_floor_point(space, sensor_height_m)
        if point is None:
            warnings.append(f"Skipped space without valid floor geometry: {space.nameString()}")
            continue

        daylight_sensor = openstudio.model.DaylightingControl(model)
        daylight_sensor.setSpace(space)
        daylight_sensor.setName(f"{space.nameString()} Daylight Sensor")
        daylight_sensor.setPosition(point)
        daylight_sensor.setPhiRotationAroundZAxis(phi_rotation_around_z_axis)
        daylight_sensor.setIlluminanceSetpoint(illuminance_setpoint)
        daylight_sensor.setLightingControlType(lighting_control_type)
        daylight_sensor.setMinimumInputPowerFractionforContinuousDimmingControl(
            minimum_input_power_fraction_continuous
        )
        daylight_sensor.setMinimumLightOutputFractionforContinuousDimmingControl(
            minimum_light_output_fraction_continuous
        )
        daylight_sensor.setNumberofSteppedControlSteps(number_of_stepped_control_steps)

        spaces_touched.append(space.nameString())
        sensors_added += 1

    if not model.save(str(output_path), True):
        print(json.dumps({"ok": False, "error": f"Failed to save output model: {output_path}"}))
        return 2

    changes = [f"Added {sensors_added} daylight sensor(s)."]
    print(
        json.dumps(
            {
                "ok": True,
                "changes": changes,
                "warnings": warnings,
                "sensors_added": sensors_added,
                "spaces_touched": spaces_touched,
                "output_model_path": str(output_path),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
