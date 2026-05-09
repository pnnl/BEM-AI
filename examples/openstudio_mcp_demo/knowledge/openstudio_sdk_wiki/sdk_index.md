---
name: sdk_index
description: Routing index for OpenStudio SDK wiki context packs.
version: 0.1.0
source_project: /Users/xuwe123/github/openstudio-standards/lib/openstudio-standards
---

# OpenStudio SDK Wiki Index

Use this index after loading `openstudio_sdk_model_editor` and before drafting a
Python script. Load only the context packs relevant to the task.

## Purpose Routing

- `sdk_core_patterns`: always load for SDK scripts unless already loaded in the
  current task. It contains load/save, optional-object, unit-conversion, and JSON
  result patterns.
- `sdk_geometry`: load for surfaces, subsurfaces, WWR, azimuth/orientation,
  exterior area, story assignment, north axis, and window area edits.
  This pack is mandatory for WWR, azimuth, orientation, cardinal direction,
  exterior-wall area, window-area, north-axis, or shading-surface scripts.
- `sdk_schedules`: load for schedule creation, schedule type limits, day
  schedules, ruleset schedules, hourly values, and schedule multipliers.
- `sdk_constructions`: load for construction layers, insulation layers,
  material thermal properties, opaque U-value edits, and simple glazing U-factor
  edits.
- `sdk_spaces_zones_loads`: load for spaces, thermal zones, plenums,
  residential/nonresidential classification, heated/cooled classification,
  internal loads, and outdoor air summaries.
- `sdk_daylighting`: load for daylighting controls and sensor placement.

## Source Domains Reviewed

The context packs are distilled from the domain folders in
`openstudio-standards/lib/openstudio-standards`, especially:

- `geometry`
- `schedules`
- `constructions`
- `space`
- `thermal_zone`
- `daylighting`
- selected `hvac`, `service_water_heating`, `weather`, and `sql_file` files

Do not copy full standards logic into generated scripts. Use these packs as SDK
idiom references and keep scripts focused on the user's model-inspection or
model-editing request.

## Script Drafting Pattern

1. Follow the context-pack selection rules in `openstudio_sdk_model_editor`.
2. Load `sdk_core_patterns`.
3. Load every domain pack required by the selected task.
4. For WWR/orientation/surface tasks, `sdk_geometry` is required.
5. Draft a bounded script using only the relevant snippets and idioms.
6. Summarize the intended script and ask for explicit user approval before
   calling `run_python`.
