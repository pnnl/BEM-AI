---
name: openstudio_sdk_model_editor
description: Inspect and edit OpenStudio models through run_python and the OpenStudio Python SDK.
version: 0.1.0
output_format: markdown_with_json_summary
---

## Scope

Use this skill only for OpenStudio model inspection and model editing. Do not use
it to run simulations or retrieve simulation results. Simulation execution,
polling, artifacts, and SQL-backed result retrieval belong to the OpenStudio MCP
tools.

Use `run_python` only when the task requires a generated Python script against a
local `.osm` file. Do not call `run_python` for tasks that can be completed with
MCP `model_*`, `sim_*`, or `results_*` tools.

Allowed uses:

- inspect spaces, thermal zones, surfaces, constructions, schedules, loads, and
  other model objects;
- compute model-level summaries from `.osm` content;
- copy a model and apply scoped edits requested by the user;
- report object counts, names, before/after values, assumptions, warnings, and
  the output model path.

Disallowed uses:

- simulation execution;
- simulation polling;
- SQL result retrieval;
- artifact retrieval;
- network calls;
- shell commands or subprocesses;
- overwriting the original model unless explicitly requested.

## Senior Modeler Workflow

1. Classify the request before writing code:
   - `inspect_only`: read model data and summarize.
   - `edit_model`: make a safe copy and edit model objects.
   - `simulate_or_results`: use MCP tools instead of `run_python`.
   - `ambiguous_or_risky`: ask a clarifying question.
2. Load SDK wiki context:
   - call `sdk_docs_route` with the user request to identify likely SDK domains,
     wiki packs, and OpenStudio classes;
   - load `sdk_index` to choose relevant examples and confirm the routing
     choice;
   - load `sdk_core_patterns` before drafting an SDK script;
   - load every required domain pack from **SDK Context-Pack Selection** below
     before drafting code;
   - when a request spans multiple domains, load all matching packs instead of
     guessing from memory.
3. Retrieve exact SDK documentation before drafting code:
   - use `sdk_docs_get_method` for constructors, setters, getters, unit-sensitive
     methods, and methods not already shown in the loaded wiki examples;
   - use `sdk_docs_list_methods` when the class is known but the exact method
     name is uncertain;
   - use `sdk_docs_search_methods` or `sdk_docs_find_classes` when the class is
     uncertain;
   - summarize important retrieved facts before writing code, especially return
     type, parameter type, units, optional values, and exception warnings.
   - if SDK docs are not configured, state that exact local SDK docs were
     unavailable and rely on loaded wiki examples plus targeted Python binding
     introspection instead of guessing.
4. Use Python binding introspection only as a targeted fallback:
   - OpenStudio docs describe the C++ API, while the Python binding may expose
     generated helper names;
   - if a collection getter or generated binding method is not present in the
     C++ docs, inspect `dir(model)` or `dir(openstudio.model.ClassName)` before
     assuming a spelling;
   - keep introspection snippets read-only and do not use them as permission to
     edit the model.
5. Confirm required inputs:
   - model path or URI;
   - target object scope, such as all spaces, a named space type, thermal zones,
     envelope surfaces, schedules, loads, constructions, or HVAC objects;
   - requested edit values and units;
   - output path when an edit is requested.
6. For any script that creates a new OpenStudio object in the model, review the
   relevant SDK wiki pattern and `sdk_docs_get_method` constructor/setter docs
   before drafting the script, then identify all required inputs:
   - object name;
   - numeric parameters and unit system;
   - referenced model objects, such as schedules, constructions, thermal zones,
     nodes, surfaces, or materials;
   - target assignment location, such as a construction layer index, air loop,
     space, zone, or building default set.
   If any required value, unit system, or referenced object is missing, ask the
   user for clarification before execution. OpenStudio setters generally expect
   SI values; if the user provides IP values, convert them before calling the
   SDK. If a setter requires another OpenStudio object, retrieve candidate
   objects from the model and ask the user to select one. If the user explicitly
   says to keep defaults, list assumptions with this exact format:
   `Object:Name.parameter: assumed to be x`.
7. Draft a short workflow before using `run_python`:
   - input model path;
   - inspection or edit target;
   - OpenStudio SDK APIs expected to be used;
   - loaded SDK wiki packs used as examples;
   - SDK documentation methods retrieved with `sdk_docs_get_method`;
   - any Python binding introspection used to verify method spelling;
   - validation checks;
   - output model path for edits.
8. For edits, never overwrite the original model unless the user explicitly asks.
   Write a new `.osm` under `outputs/` or another user-approved path.
9. Prepare a bounded Python script for `run_python`, or split the task into
   multiple scripts when the scope is complex. Use the script-length rules
   below.
10. Summarize like a senior building energy modeler:
   - what was inspected or changed;
   - affected object counts and names when practical;
   - before/after values for edits;
   - assumptions and unresolved issues;
   - output model path;
   - recommended next step, usually validation or simulation via MCP.

## SDK Context-Pack Selection

Always load `sdk_index` and `sdk_core_patterns` first for SDK scripts. Then load
the domain packs below based on the requested inspection or edit. Do not draft
the Python script until all matching packs are loaded.

- Load `sdk_geometry` for geometry, building stories, spaces as geometric
  containers, surfaces, subsurfaces, exterior walls, roofs, floors, WWR,
  window/skylight/door area, shading surfaces, azimuth, orientation, cardinal
  direction, north axis, centroid/vertex edits, or envelope area summaries.
- Load `sdk_spaces_zones_loads` for spaces, thermal zones, plenums,
  part-of-total-floor-area flags, zone multipliers, internal loads, people,
  lights, electric/gas equipment, load densities, outdoor air, and
  space/zone-level summary tables.
- Load both `sdk_geometry` and `sdk_spaces_zones_loads` when a geometry task
  also needs space or zone multipliers, thermal-zone grouping, floor area by
  zone, or load summaries by space.
- Load `sdk_constructions` for construction assignments, construction layers,
  opaque materials, massless or standard material R-values, U-factor changes,
  insulation edits, simple glazing, SHGC, visible transmittance, and
  construction summaries by surface type.
- Load both `sdk_geometry` and `sdk_constructions` when summarizing envelope
  areas by construction, editing fenestration constructions, or changing
  constructions on selected surfaces/subsurfaces.
- Load `sdk_schedules` for schedule rulesets, schedule type limits, day
  schedules, hourly profiles, multipliers, occupancy/lighting/equipment
  schedules, and schedule value edits.
- Load both `sdk_schedules` and `sdk_spaces_zones_loads` when inspecting or
  editing loads that depend on schedules.
- Load `sdk_daylighting` for daylighting controls, daylight sensors, sensor
  position, illuminance setpoints, duplicate daylighting controls, and
  daylighting-related model edits.
- Load both `sdk_daylighting` and `sdk_geometry` when sensor placement depends
  on floor vertices, space geometry, exterior fenestration, or centroid points.
- Load `sdk_hvac` for air-loop topology, plant-loop topology, zone equipment,
  thermostats, setpoint managers, coils, fans, outdoor air controllers, sizing
  objects, HVAC availability schedules, and served-zone summaries.
- Load `openstudio_vav_reheat_system_creator` in addition to `sdk_hvac` when
  the user asks to add, create, prototype, or draft a multi-zone VAV reheat
  system. That skill owns the VAV system creation sequence and required
  clarification gates.
- Load both `sdk_hvac` and `sdk_spaces_zones_loads` when HVAC information needs
  to be summarized by space, thermal zone, or served zone.
- Load `sdk_simulation_results` only to explain or review OpenStudio simulation
  files, OSW setup, SQL attachment, or result-extraction idioms. Do not use this
  pack as permission to run simulations or retrieve results through
  `run_python`; route actual simulation and result workflows to MCP `sim_*` and
  `results_*`.
- Load `sdk_review_prompts` only when testing or reviewing the knowledge-base
  routing behavior.

Required geometry rule: if a script uses `surface.azimuth()`, it must use the
`surface_azimuth_degrees(surface)` helper from `sdk_geometry`. Do not treat raw
`surface.azimuth()` as degrees and do not manually convert with `math.pi`.
If needed, verify this with `sdk_docs_get_method` for
`PlanarSurface.azimuth`, which documents the angle in radians.

Required OpenStudio API naming rule: follow the exact SDK method spelling shown
in the loaded wiki examples. Some OpenStudio collection getters use historical
plural spellings that do not match common English pluralization. For building
stories, use the `sdk_geometry` example spelling exactly:
`model.getBuildingStorys()`. If a generated Python collection getter is not
present in the C++ SDK docs, verify it with Python binding introspection before
drafting code.

Required object-creation rule: when creating a new OpenStudio object, do not
draft or execute the script until required names, numeric values, units,
referenced model objects, and assignment targets are known. If missing, ask the
user. If defaults are approved, list each assumption as
`Object:Name.parameter: assumed to be x`.

## Script Length And Multi-Step Rules

Prefer small, inspectable scripts. The `run_python` tool records script length
metadata and logs failed executions for later experience review, but the agent
must still keep scripts reviewable.

- For scripts up to 120 lines, a single script is acceptable when the task is
  scoped and clear.
- For scripts over 120 lines, provide a section map before execution and make
  sure the full script is visible to the user as a fenced `python` block or text
  artifact.
- For scripts over 250 lines, do not execute as one script unless the user
  explicitly approves a single long script. Split the work into phases instead.

Use multi-step scripting for complex model edits, especially HVAC creation,
multi-object schedule edits, construction library changes, and workflows that
need user choices. The default phases are:

1. **Preflight inspection**: read the model and report candidate zones,
   schedules, loops, systems, constructions, or target objects.
2. **Clarification gate**: ask the user to select missing objects, units,
   defaults, and assumptions.
3. **Focused edit script**: make one scoped copy/edit/save operation.
4. **Validation script or MCP validation**: verify object counts, assignments,
   warnings, and output model path.
5. **Simulation handoff**: use MCP `sim_*` and `results_*` tools when simulation
   or result retrieval is requested.

When a `run_python` execution fails, do not immediately retry from memory. Read
the error, identify the failed SDK call or assumption, check loaded wiki context
or SDK docs for the relevant class/method, then draft a shorter corrected script
or debugging script. After three failed attempts, stop and ask the user to
review the script and failure summary.

## Required Script Result Contract

The Python script should print one final JSON object with these fields:

```json
{
  "ok": true,
  "mode": "inspect_only|edit_model",
  "input_model_path": "...",
  "output_model_path": "...",
  "changes": [],
  "warnings": [],
  "counts": {},
  "summary": "..."
}
```

If the task fails, print:

```json
{
  "ok": false,
  "error": "Clear failure reason.",
  "warnings": []
}
```

## Safety Rules

- Use `openstudio.openstudioosversion.VersionTranslator().loadModel(str(input_path))`
  for loading.
- Check `is_initialized()` before accessing the model.
- Save edited models with `model.save(str(output_path), True)`.
- Preserve the original model file.
- Keep scripts deterministic and local-file only.
- Do not import modules blocked by the `run_python` tool policy:
  `subprocess`, `socket`, `requests`, `urllib`, or `ctypes`.
- Do not import network libraries.
- Do not use shell commands or subprocesses.
- Do not perform simulation or results retrieval with `run_python`.
