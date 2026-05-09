# OpenStudio SDK Recipes for `run_python`

These recipes are intentionally small and local-file focused. They are context
for drafting Python scripts that inspect or edit `.osm` files through the
OpenStudio Python SDK.

## Dynamic SDK Wiki Packs

For task-specific examples, load the OpenStudio SDK wiki packs through the
agent's `load_skill` tool. These packs are kept separate so the agent can load
only the examples needed for the current request.

- `sdk_index`: routing index for the SDK wiki.
- `sdk_core_patterns`: load/save, optional-object handling, casts, unit
  conversion, object lookup, and JSON result patterns.
- `sdk_geometry`: WWR, orientation, surface/subsurface renaming, north axis,
  and window area edits.
- `sdk_schedules`: schedule type limits, constant schedules, ruleset schedules,
  hourly values, and schedule multipliers.
- `sdk_constructions`: construction layers, insulation layer edits, opaque
  material edits, and simple glazing U-factor edits.
- `sdk_spaces_zones_loads`: space/zone summaries, plenums, internal load
  summaries, and outdoor air summaries.
- `sdk_daylighting`: daylighting control creation and duplicate-sensor checks.

Start with `sdk_index`, then load `sdk_core_patterns` and one domain pack.

## Import Safety

Generated `run_python` scripts must stay local-file only. Do not import modules
blocked by the tool policy: `subprocess`, `socket`, `requests`, `urllib`, or
`ctypes`.

## Load and Save

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
    print(json.dumps({"ok": False, "error": f"Failed to load model: {input_path}"}))
    raise SystemExit(2)

model = model_optional.get()

# inspect or edit model here

if not model.save(str(output_path), True):
    print(json.dumps({"ok": False, "error": f"Failed to save model: {output_path}"}))
    raise SystemExit(2)
```

## Inspect Model Counts

```python
def safe_count(model, getter_name):
    getter = getattr(model, getter_name, None)
    return len(getter()) if callable(getter) else None

counts = {
    "spaces": len(model.getSpaces()),
    "thermal_zones": len(model.getThermalZones()),
    "building_stories": len(model.getBuildingStorys()),
    "space_types": len(model.getSpaceTypes()),
    "surfaces": len(model.getSurfaces()),
    "sub_surfaces": len(model.getSubSurfaces()),
    "constructions": len(model.getConstructions()),
    "lights": safe_count(model, "getLights"),
    "electric_equipment": safe_count(model, "getElectricEquipments"),
    "people": safe_count(model, "getPeople"),
}
```

## List Spaces and Thermal Zones

```python
rows = []
for space in model.getSpaces():
    zone = space.thermalZone()
    rows.append({
        "space": space.nameString(),
        "thermal_zone": zone.get().nameString() if zone.is_initialized() else None,
        "floor_area_m2": space.floorArea(),
        "volume_m3": space.volume(),
    })
```

## Reduce Lighting Power Definitions

```python
factor = 0.8
changes = []
lights_getter = getattr(model, "getLights", None)
lights_objects = list(lights_getter()) if callable(lights_getter) else []

for lights in lights_objects:
    definition = lights.lightsDefinition()
    name = lights.nameString()
    before = {
        "watts_per_space_floor_area": None,
        "lighting_level": None,
    }

    lpd = definition.wattsperSpaceFloorArea()
    if lpd.is_initialized():
        old = lpd.get()
        definition.setWattsperSpaceFloorArea(old * factor)
        before["watts_per_space_floor_area"] = old
        changes.append({
            "object": name,
            "field": "wattsperSpaceFloorArea",
            "before": old,
            "after": old * factor,
        })
        continue

    level = definition.lightingLevel()
    if level.is_initialized():
        old = level.get()
        definition.setLightingLevel(old * factor)
        before["lighting_level"] = old
        changes.append({
            "object": name,
            "field": "lightingLevel",
            "before": old,
            "after": old * factor,
        })
```

## Inspect Constructions Used by Exterior Surfaces

```python
constructions = {}
for surface in model.getSurfaces():
    if surface.outsideBoundaryCondition().lower() != "outdoors":
        continue
    construction = surface.construction()
    constructions[surface.nameString()] = (
        construction.get().nameString() if construction.is_initialized() else None
    )
```

## Final JSON Print

```python
print(json.dumps({
    "ok": True,
    "mode": "edit_model",
    "input_model_path": str(input_path),
    "output_model_path": str(output_path),
    "changes": changes,
    "warnings": warnings,
    "counts": counts,
    "summary": "Reduced lighting power definitions by 20 percent.",
}, indent=2))
```
