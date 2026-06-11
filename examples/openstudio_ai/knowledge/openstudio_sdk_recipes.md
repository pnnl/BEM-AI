# OpenStudio SDK Knowledge Base

This file is the lightweight entry point for OpenStudio Python SDK context. It
should stay small. Detailed examples live in `knowledge/openstudio_sdk_wiki/` and
are loaded only when relevant to the user request.

The larger source-review note is
`examples/openstudio_ai/OPENSTUDIO_SDK_EXPERIENCE.md`. Treat it as a human
reference, not default agent context.

## Load Order

For any `run_python` task that inspects or edits an `.osm` model:

1. Load `openstudio_sdk_model_editor`.
2. Load `sdk_index`.
3. Load `sdk_core_patterns`.
4. Load only the domain packs needed for the task.
5. Show the complete Python script and ask for explicit approval before running
   it.

## Context Packs

- `sdk_index`: routing index and source coverage.
- `sdk_core_patterns`: load/save, optional-object handling, casts, unit
  conversion, object lookup, historical Python SDK names, safe-copy edits, and
  JSON result contract.
- `sdk_geometry`: spaces as geometry containers, surfaces, subsurfaces, WWR,
  azimuth/orientation, building stories, north axis, bounding boxes, transforms,
  and window area edits.
- `sdk_constructions`: construction assignments, construction layers, material
  properties, massless/standard opaque materials, simple glazing,
  F-factor slabs, C-factor underground walls, and default construction sets.
- `sdk_schedules`: schedule type limits, ruleset schedules, day schedules,
  hourly values, date ranges, default schedule sets, and space-type standards
  tags.
- `sdk_spaces_zones_loads`: spaces, thermal zones, additional properties,
  plenums, floor area, internal loads, outdoor air, and zone/space grouping.
- `sdk_daylighting`: daylighting controls, sensor placement, primary/secondary
  controls, and daylighting fraction safeguards.
- `sdk_hvac`: air-loop topology, zone equipment, coils, fans, thermostats,
  setpoint managers, outdoor air controllers, and sizing objects.
- `sdk_simulation_results`: OpenStudio simulation-file and SQL idioms for
  explanation/review only. Actual simulation and result retrieval should use MCP
  `sim_*` and `results_*` tools.
- `sdk_review_prompts`: 12 representative prompts and pass criteria for
  reviewing routing and context-load behavior.

## Routing Summary

- Model summary: `sdk_geometry`, `sdk_spaces_zones_loads`.
- WWR, facade orientation, azimuth, window area edits: `sdk_geometry`.
- Construction and material inspection/editing: `sdk_constructions`, often with
  `sdk_geometry`.
- Schedule inspection/editing: `sdk_schedules`, often with
  `sdk_spaces_zones_loads`.
- Internal load inspection/editing: `sdk_spaces_zones_loads`, often with
  `sdk_schedules`.
- HVAC topology: `sdk_hvac`, often with `sdk_spaces_zones_loads`.
- Daylighting edits: `sdk_daylighting`, often with `sdk_geometry`.
- Simulation runs, polling, artifacts, and result summaries: MCP tools, not
  `run_python`.

## Non-Negotiable SDK Rules

- Use `openstudio.openstudioosversion.VersionTranslator()` for default model
  loading examples.
- Check optionals before `.get()` unless a project-specific precondition is
  explicit.
- Keep OpenStudio's historical Python method names exactly as source-backed
  examples show them, including `getBuildingStorys()`.
- Convert `surface.azimuth()` from radians to degrees with
  `openstudio.convert(surface.azimuth(), "rad", "deg")`.
- Do not import blocked modules: `subprocess`, `socket`, `requests`, `urllib`,
  or `ctypes`.
- For edits, write to a copied output model path and preserve the original.
- Before creating a new OpenStudio object, identify required names, numeric
  values, unit systems, referenced model objects, and assignment targets. Ask the
  user for anything missing. Convert IP inputs to SI before SDK setters. If the
  user approves defaults, list assumptions as
  `Object:Name.parameter: assumed to be x`.
