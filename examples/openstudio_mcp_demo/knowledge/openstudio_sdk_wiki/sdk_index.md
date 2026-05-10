---
name: sdk_index
description: Routing index for OpenStudio SDK wiki context packs.
version: 0.1.0
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
- `sdk_hvac`: load for air loops, zone equipment, coils, fans, thermostats,
  sizing objects, outdoor air controllers, setpoint managers, and HVAC topology
  inspection.
- `sdk_simulation_results`: load for understanding OpenStudio simulation-file,
  OSW, SQL, and result-query idioms. In this demo, use MCP `sim_*` and
  `results_*` tools for actual simulation and result retrieval; do not use this
  pack as permission to run simulations with `run_python`.
- `sdk_review_prompts`: load only when testing or reviewing the knowledge-base
  behavior. It contains representative prompts and success criteria.

## Source Review Scope

These packs are distilled from OpenStudio standards-style examples and
source-reviewed Python SDK usage in adjacent building-modeling projects. Do not
publish local source paths in agent-facing context. Do not copy full standards
logic into generated scripts. Use these packs as SDK idiom references and keep
scripts focused on the user's model-inspection or model-editing request.

## Script Drafting Pattern

1. Follow the context-pack selection rules in `openstudio_sdk_model_editor`.
2. Load `sdk_core_patterns`.
3. Load every domain pack required by the selected task.
4. For WWR/orientation/surface tasks, `sdk_geometry` is required.
5. For HVAC topology tasks, load `sdk_hvac`; for simulations and result
   retrieval, route to MCP tools instead of `run_python`.
6. Draft a bounded script using only the relevant snippets and idioms.
7. Summarize the intended script and ask for explicit user approval before
   calling `run_python`.
