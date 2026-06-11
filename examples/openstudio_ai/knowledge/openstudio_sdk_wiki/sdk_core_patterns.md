---
name: sdk_core_patterns
description: Core OpenStudio Python SDK scripting patterns for bounded model inspection and editing.
version: 0.1.0
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

## Alternate Source-Observed Model Load

`openstudio.model.Model.load(...)` is also used in reviewed source. It returns
an optional model and must be checked before `.get()`.

```python
model_optional = openstudio.model.Model.load(str(input_path))
if not model_optional.is_initialized():
    raise ValueError(f"Failed to load model: {input_path}")
model = model_optional.get()
```

Use a version-translator compatibility helper as the default in OpenStudio AI
generated scripts unless a project-specific reason requires
`openstudio.model.Model.load(...)`. Some bindings expose
`openstudio.openstudioosversion.VersionTranslator()` and others expose
`openstudio.osversion.VersionTranslator()`.

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

`getObjectByTypeAndName(...)` is commonly checked with `.empty()` in reviewed
project code.

```python
optional_obj = model.getObjectByTypeAndName(
    openstudio.model.Space.iddObjectType(),
    space_name,
)
if optional_obj.empty():
    warnings.append(f"No Space named {space_name} was found.")
else:
    space = optional_obj.get().to_Space().get()
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
boundary and report units explicitly. `openstudio.convert(...)` returns an
optional conversion result; check it when inputs may be invalid.

```python
def convert_or_raise(value, from_unit, to_unit):
    result = openstudio.convert(value, from_unit, to_unit)
    if not result.is_initialized():
        raise ValueError(f"Could not convert {value} from {from_unit} to {to_unit}.")
    return result.get()

floor_area_ft2 = convert_or_raise(model.getBuilding().floorArea(), "m^2", "ft^2")
```

## Creating New OpenStudio Objects

Before drafting or executing a script that creates a new OpenStudio object in a
model, review the constructor and setter calls in the relevant example and
identify every required input.

If the user did not provide the value, unit system, target object, or referenced
model object, ask for clarification before execution. Do not silently invent
inputs for new model objects unless the user explicitly says to keep defaults.

When the user provides numbers, confirm units. OpenStudio setters generally
expect SI values, so convert IP inputs before calling SDK setters.

When an object requires another OpenStudio object, inspect the expected data
type from the method call and retrieve matching existing model objects for user
selection. For example, `setMinimumOutdoorAirSchedule(hvac_schedule)` requires
an OpenStudio schedule object, so list candidate schedules from the model and
ask the user which one to use.

If the user approves defaults, list assumptions in this exact format:

```text
Object:Name.parameter: assumed to be x
```

Example:

```text
FFactorGroundFloorConstruction:Unheated Slab F-Factor.area: assumed to be 100.0 m^2
ControllerOutdoorAir:New OA Controller.minimumOutdoorAirSchedule: assumed to be Always On Discrete
```

## Historical Python SDK Names

OpenStudio Python method names sometimes preserve historical/non-English
pluralization or capitalization. Use names exactly as shown in source-backed
examples.

```python
building_story_count = len(model.getBuildingStorys())
gas_material_count = len(model.getGass())
default_set.setNumberofPeopleSchedule(occupancy_schedule)
day_schedule.setInterpolatetoTimestep("No")
```

Do not invent natural-English variants such as `getBuildingStories()` or
`getGases()` without checking the active SDK.

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
    "building_stories": len(model.getBuildingStorys()),
    "surfaces": len(model.getSurfaces()),
    "sub_surfaces": len(model.getSubSurfaces()),
    "constructions": len(model.getConstructions()),
    "lights": safe_count(model, "getLights"),
    "electric_equipment": safe_count(model, "getElectricEquipments"),
    "people": safe_count(model, "getPeople"),
}
```

## Safe Copy Pattern for Edits

For model edits, write to a copied output path and preserve the original input.

```python
output_path = Path("outputs/model_edited.osm").resolve()
output_path.parent.mkdir(parents=True, exist_ok=True)

# make model edits here

if not model.save(str(output_path), True):
    raise ValueError(f"Failed to save edited model: {output_path}")
```
