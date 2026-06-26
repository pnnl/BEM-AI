# Harness Runtime Learning Pipeline

The harness pipeline runs in a distributable agent plugin. It may capture local
experience and propose reusable assets, but it must not directly update trusted
OpenStudio AI assets.

Allowed outputs:

- local recipes;
- session lessons;
- candidate measures;
- candidate eval cases;
- candidate knowledge-base notes.

Promotion into trusted assets is handled by the developer pipeline.

## Exported Runtime Shape

Claude and Codex plugin exports include:

- `learning/README.md`
- `learning/schemas/candidate_measure.schema.json`
- `learning/schemas/candidate_recipe.schema.json`
- `learning/schemas/session_lesson.schema.json`
- `learning/candidates/.gitkeep`

Claude exports also include `/openstudio-ai:propose-measure`, which instructs
the host agent to write candidate measure JSON into `learning/candidates/`.
