---
name: sdk_core_patterns
description: Core OpenStudio Python SDK scripting patterns for bounded model inspection and editing.
version: 0.1.0
source_domains:
  - openstudio-standards/weather
  - openstudio-standards/geometry
  - openstudio-standards/schedules
---

# Core OpenStudio SDK Patterns

Use these patterns in every `run_python` script that reads or edits an `.osm`
model.

## Import Safety

Generated scripts must stay local-file only. Do not import modules blocked by
the `run_python` tool policy: `subprocess`, `socket`, `requests`, `urllib`, or
`ctypes`.

## Load, Save, and Report

```python
import json
from pathlib import Path
import openstudio

input_path = Path("resource/sample.osm").resolve()
output_path = Path("outputs/sample_edited.osm").resolve()
output_path.parent.mkdir(parents=True, exist_ok=True)

translator = openstudio.openstudioosversion.VersionTranslator()
model_optional = translator.loadModel(str(input_path))
if not model_optional.is_initialized():
    print(json.dumps({
        "ok": False,
        "error": f"Failed to load model: {input_path}",
        "warnings": [],
    }))
    raise SystemExit(2)

model = model_optional.get()
changes = []
warnings = []
counts = {}

# inspect or edit model here

if not model.save(str(output_path), True):
    print(json.dumps({
        "ok": False,
        "error": f"Failed to save model: {output_path}",
        "warnings": warnings,
    }))
    raise SystemExit(2)

print(json.dumps({
    "ok": True,
    "mode": "inspect_only_or_edit_model",
    "input_model_path": str(input_path),
    "output_model_path": str(output_path),
    "changes": changes,
    "warnings": warnings,
    "counts": counts,
    "summary": "Short human-readable summary.",
}, indent=2))
```

For inspect-only scripts, omit `model.save(...)` and set `output_model_path` to
`None`.

## Optional Objects

OpenStudio methods often return optional wrapper objects. Always check
`is_initialized()` before calling `.get()`.

```python
zone_opt = space.thermalZone()
zone_name = zone_opt.get().nameString() if zone_opt.is_initialized() else None

construction_opt = surface.construction()
construction_name = (
    construction_opt.get().nameString()
    if construction_opt.is_initialized()
    else None
)
```

## Type Casts

Some methods return base model objects. Cast them before using subtype-specific
methods.

```python
ruleset_opt = schedule.to_ScheduleRuleset()
if ruleset_opt.is_initialized():
    ruleset = ruleset_opt.get()
    default_day = ruleset.defaultDaySchedule()
```

## Unit Conversion

Keep calculations in SI unless the user asks for IP values. Convert at the
boundary and report units explicitly.

```python
floor_area_ft2 = openstudio.convert(model.getBuilding().floorArea(), "m^2", "ft^2").get()
target_u_si = openstudio.convert(target_u_ip, "Btu/ft^2*hr*R", "W/m^2*K").get()
```

## Object Lookup by Name

Prefer explicit name matching for targeted edits. Report when no objects match.

```python
def name_matches(obj, target):
    return obj.nameString().strip().lower() == target.strip().lower()

matches = [space for space in model.getSpaces() if name_matches(space, "Core_ZN")]
if not matches:
    warnings.append("No space named Core_ZN was found.")
```

## Safe Count Helper

SDK getter names can vary by object type. Use direct getters when known and a
small safe helper when inspecting broad object categories.

```python
def safe_count(obj, getter_name):
    getter = getattr(obj, getter_name, None)
    return len(getter()) if callable(getter) else None

counts = {
    "spaces": len(model.getSpaces()),
    "thermal_zones": len(model.getThermalZones()),
    "surfaces": len(model.getSurfaces()),
    "sub_surfaces": len(model.getSubSurfaces()),
    "constructions": len(model.getConstructions()),
    "lights": safe_count(model, "getLights"),
    "electric_equipment": safe_count(model, "getElectricEquipments"),
    "people": safe_count(model, "getPeople"),
}
```
