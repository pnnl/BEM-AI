# HVAC Child Skill Management

This document describes the developer-facing management layer for the generated
OpenStudio AI HVAC child skills. It is a build-time authoring tool for the
skill library, not a runtime orchestration system.

## Purpose

The low-level HVAC child skills are committed markdown files at runtime, but
they are maintained from a centralized source of truth:

- specs directory: `examples/openstudio_ai/skills/specs/hvac/`
- template: `examples/openstudio_ai/skills/templates/hvac_child_skill.md.j2`
- generator: `examples/openstudio_ai/scripts/generate_hvac_child_skills.py`

The agent still loads normal `.md` skill files from the registry. The generator
exists to improve consistency, keep the child contracts short, and make it
easier to trim repeated context across the skill set.

## Managed Skills

The generator owns these child skills:

- `openstudio_hvac_air_loop_creator`
- `openstudio_hvac_schedule_resolver`
- `openstudio_hvac_sizing_system_configurator`
- `openstudio_hvac_supply_fan_creator`
- `openstudio_hvac_central_heating_coil_creator`
- `openstudio_hvac_central_cooling_coil_creator`
- `openstudio_hvac_outdoor_air_system_creator`
- `openstudio_hvac_vav_terminal_creator`
- `openstudio_hvac_system_validator`

The generator does not own:

- `openstudio_vav_reheat_system_creator`
- `openstudio_hvac_workflow_state`
- `openstudio_sdk_model_editor`
- `hvac_sizing_assistant`

## Why This Exists

The current child skills share the same structural contract:

- scope
- required state
- optional state
- SDK methods to verify
- code pattern
- missing-field behavior
- `state_patch`
- validation checks

Maintaining that structure manually invites drift and repeated wording. The
spec/template split makes it easier to:

- keep child skills consistent;
- tighten or shorten shared phrasing in one place;
- add new HVAC child skills without cloning markdown by hand;
- add tests that detect drift between the source spec and committed skill files.

It also creates one place to enforce a disciplined contract for every child
skill:

- what state the child can trust;
- what it must ask for before drafting code;
- what it is allowed to mutate;
- what it must return to the parent workflow.

## Source Format

Each child skill spec file in `skills/specs/hvac/` should declare:

- `name`
- `description`
- `scope`
- `exclusions`
- `required_state`
- optional `conditional_required_state`
- `optional_state`
- optional `sdk_methods_intro`
- `sdk_methods`
- `code_pattern`
- `missing_field_behavior`
- `state_patch`
- `validation_checks`
- optional `extra_sections`

`extra_sections` is reserved for cases like the validator skill where an
additional JSON example or a handoff rule is still useful.

## Contract Model

Each generated child skill follows the same developer-facing contract:

1. `Scope`
   Defines the exact phase boundary for the child skill.
2. `Required State Fields`
   Lists state that must already exist on the blackboard or workflow state.
3. `Optional State Fields`
   Lists values the child may use when present but must not assume.
4. `SDK Methods To Verify`
   Points the coding agent at the exact SDK methods it should confirm before
   writing code.
5. `Code Pattern`
   Captures the intended sequence for that phase.
6. `Missing Field Behavior`
   Defines when the child should stop and ask for clarification instead of
   guessing.
7. `State Patch`
   Defines the parent-owned mutation contract. The child returns a patch; the
   parent decides how to apply it.
8. `Validation Checks`
   Defines what the child should verify before handing control back.

This keeps the child skills narrow and lets the parent workflow remain the
owner of orchestration, blackboard updates, and cross-phase decisions.

## Generator Workflow

Regenerate child skills:

```bash
.venv/bin/python examples/openstudio_ai/scripts/generate_hvac_child_skills.py
```

Check for drift without rewriting files:

```bash
.venv/bin/python examples/openstudio_ai/scripts/generate_hvac_child_skills.py --check
```

The `--check` mode is what tests should use.

Expected edit cycle:

1. change one YAML skill spec;
2. change the template only if the shared contract should change;
3. regenerate the markdown skills;
4. run the drift test;
5. review the generated markdown diff as the real runtime artifact.

## Editing Rules

When changing a managed child skill:

1. Edit the YAML spec, not the generated `.md` file.
2. Adjust the Jinja template only when the shared structure should change for
   all managed child skills.
3. Run the generator.
4. Run the drift test.

Do not hand-edit generated child skills unless you are immediately moving the
same change back into the YAML spec or template.

## Directory Layout

The management tool is intentionally simple:

- `skills/specs/hvac/*.yaml`
  One structured source file per managed child skill.
- `skills/templates/hvac_child_skill.md.j2`
  The shared markdown contract template.
- `scripts/generate_hvac_child_skills.py`
  The renderer/checker for committed skill files.
- `skills/openstudio_hvac_*.md`
  The runtime markdown artifacts loaded by the agent system.

The runtime should treat the generated `.md` files as stable inputs. The spec
and template are developer-maintenance assets.

## When To Change The Template

Change the template when you want to alter shared structure or repeated phrasing
across all child skills. Examples:

- shorten common wording;
- change section order;
- add one new required section for every child skill;
- change how numbered code-pattern steps render.

Do not change the template for phase-specific logic.

## When To Change The Spec

Change an individual YAML spec file when a single child skill needs a different:

- required state field;
- SDK method list;
- code pattern;
- patch example;
- validation check;
- missing-field rule.

Also change the spec when:

- a new child skill is added to the hierarchy;
- a state field is renamed in the parent workflow;
- the child should return a different `state_patch` shape;
- the validation policy changes for one phase only.

## Runtime Boundary

This is a build-time management tool, not a runtime dynamic-skill system.

At runtime:

- the agent still loads committed markdown skills from the skill registry;
- no child skill markdown is generated during a user turn;
- the parent skill still controls which child skill is loaded per phase.

That keeps runtime behavior inspectable and stable.

## Relationship To The Blackboard

This tool does not replace the blackboard. It complements it.

- The blackboard stores workflow state across turns and across loaded skills.
- The child skill markdown tells the agent how to interpret that state for one
  narrow phase.
- The child returns a `state_patch`.
- The parent workflow or coordinator remains the only owner of applying that
  patch to shared state.

That separation matters. It prevents a low-level child skill from silently
rewriting shared assumptions or phase status.

## Adding A New Child Skill

Use this sequence:

1. Add one new `*.yaml` file under `skills/specs/hvac/`.
2. Reuse the shared template unless the contract itself truly changes.
3. Regenerate the markdown output.
4. Confirm the new skill is referenced by the parent orchestration skill only
   in the phase where it belongs.
5. Add or update an evaluation if the new child changes planning behavior.

If a new skill cannot fit the shared contract, that is usually a sign that the
phase boundary is still too broad and should be split again.

## Why One File Per Skill

This layout is preferred over one monolithic YAML because it gives:

- smaller diffs for phase-specific changes;
- lower merge conflict risk across parallel HVAC work;
- clearer review because one spec file maps to one runtime skill;
- simpler ownership when different child skills evolve at different speeds.

The generator discovers all `*.yaml` files in `skills/specs/hvac/`. A separate
manifest is not required unless we later need explicit ordering or opt-in
publication rules.

## Testing Expectations

The management layer should be protected by a drift test that:

- renders all managed skills from the spec/template;
- compares rendered output to committed markdown files;
- fails if the committed files are out of sync.

This keeps the centralized source of truth authoritative.

Recommended focused checks:

```bash
.venv/bin/python examples/openstudio_ai/scripts/generate_hvac_child_skills.py --check
.venv/bin/python -m pytest -q tests/test_openstudio_hvac_skill_generation.py
```

If either check fails, fix the spec/template mismatch before touching the parent
workflow logic.
