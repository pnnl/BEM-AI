---
name: sdk_review_prompts
description: Representative prompts and pass criteria for reviewing OpenStudio SDK knowledge-pack routing.
version: 0.1.0
---

# SDK Knowledge-Base Review Prompts

Use these prompts to review whether the OpenStudio agent loads the right context
packs, avoids context overload, drafts correct SDK scripts, and routes
simulation/result workflows to MCP tools.

## Required Pass Criteria

For every SDK-script prompt, the agent should:

- load `openstudio_sdk_model_editor`;
- load `sdk_index` and `sdk_core_patterns`;
- load only the matching domain packs;
- show the full Python script before execution;
- ask for explicit user approval before calling `run_python`;
- use `openstudio.openstudioosversion.VersionTranslator()` unless it gives a
  clear project-specific reason not to;
- avoid fake SDK names such as `getBuildingStories()`;
- use `model.getBuildingStorys()` for building stories;
- use OpenStudio unit conversion for `surface.azimuth()` radians to degrees;
- preserve the input model and write edits to a copied output path;
- for any new OpenStudio object, ask for missing names, numeric values, units,
  referenced model objects, and assignment targets before execution;
- list approved default assumptions as `Object:Name.parameter: assumed to be x`;
- stop after three failed `run_python` attempts and report likely causes.

For simulation/result prompts, the agent should route to MCP `model_*`,
`sim_*`, and `results_*` tools instead of launching simulations through
`run_python`.

## 12 Representative Prompts

### 1. Model Summary

Inspect `resource/sample.osm` and summarize building type, floor area, spaces,
zones, stories, surfaces, and subsurfaces.

Expected packs: `sdk_core_patterns`, `sdk_geometry`,
`sdk_spaces_zones_loads`.

### 2. Geometry and WWR

Compute overall WWR and WWR by cardinal orientation. Include exterior wall area,
window area, and assumptions.

Expected packs: `sdk_core_patterns`, `sdk_geometry`.

### 3. Azimuth-Sensitive Facade Review

List exterior walls with azimuth, cardinal direction, gross area, subsurface
area, and space name.

Expected packs: `sdk_core_patterns`, `sdk_geometry`.

### 4. Construction Inspection

Inspect all constructions used by exterior walls, roofs, floors, windows,
skylights, and doors. List layers and material names.

Expected packs: `sdk_core_patterns`, `sdk_geometry`, `sdk_constructions`.

### 5. Material Thermal Properties

For exterior opaque constructions, extract material thickness, conductivity,
density, specific heat, and thermal resistance where available.

Expected packs: `sdk_core_patterns`, `sdk_constructions`.

### 6. Fenestration Properties

Inspect window, skylight, and glass door constructions. Report U-factor, SHGC,
VT, and where those values are stored.

Expected packs: `sdk_core_patterns`, `sdk_geometry`, `sdk_constructions`.

### 7. Schedule Inspection

Inspect occupancy, lighting, equipment, thermostat, and HVAC availability
schedules by space type or thermal zone.

Expected packs: `sdk_core_patterns`, `sdk_schedules`,
`sdk_spaces_zones_loads`, `sdk_hvac`.

### 8. Internal Loads

Summarize people, lights, electric equipment, gas equipment, and outdoor air
loads by space and space type.

Expected packs: `sdk_core_patterns`, `sdk_spaces_zones_loads`,
`sdk_schedules`.

### 9. HVAC Topology

Inspect air loops, plant loops, zone equipment, thermostats, setpoint managers,
coils, fans, and served zones.

Expected packs: `sdk_core_patterns`, `sdk_hvac`,
`sdk_spaces_zones_loads`.

### 10. Safe Model Edit

Create a copy of the model and reduce lighting power by 20 percent. Print the
full script before running and summarize every changed object.

Expected packs: `sdk_core_patterns`, `sdk_spaces_zones_loads`,
`sdk_schedules`.

### 11. Envelope Edit with Rerun Intent

Create a copied model with south-facing WWR reduced to 20 percent, save it, and
explain what simulation should be rerun afterward.

Expected packs: `sdk_core_patterns`, `sdk_geometry`, `sdk_constructions`.
After the edit, route validation/simulation to MCP `model_*` and `sim_*`.

### 12. Debugging Resilience

Try to inspect building stories, schedules, and construction sets, but handle
missing SDK methods or missing optionals gracefully and report failures.

Expected packs: `sdk_core_patterns`, `sdk_geometry`, `sdk_schedules`,
`sdk_constructions`.

## Review Notes

- Passing does not require executing all prompts automatically. The review can
  be manual or scripted against agent traces.
- A failure to load a required pack is a context-routing bug.
- Loading many unrelated packs for a narrow prompt is a context-overload bug.
- Producing a partial script without showing the full Python block is a safety
  and UX bug.
