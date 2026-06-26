# OpenStudio AI Learning Pipelines

OpenStudio AI uses two separate learning pipelines.

Developer pipeline:

- captures raw usage, failures, warnings, and corrections;
- distills them into candidate lessons or assets;
- sends candidates through review;
- validates with evals;
- promotes approved assets into trusted knowledge, skills, SDK index notes, or
  MCP measures.

Harness pipeline:

- runs inside a distributable harness;
- captures local repeated scripts, recipes, and session lessons;
- proposes candidate measures or reusable recipes;
- stores candidates locally for review;
- never directly edits trusted assets.

This separation keeps "AI learns" defensible: runtime observations can create
candidates, but trusted assets require review and validation.

## Developer Pipeline

Run the deterministic developer curation pass:

```bash
.venv/bin/python -m examples.openstudio_ai.learning.developer_pipeline.run_pipeline
```

It reads:

- `logs/python_script_failure_experience.jsonl`
- `logs/telemetry.jsonl`

It writes reviewable candidates to:

- `learning/review_queue/`

These candidates are not trusted assets. A modeler/developer must review them,
add or update evals, and then promote them intentionally.

## Runtime Harness Pipeline

Claude/Codex exports include a lightweight runtime learning area:

- `learning/README.md`
- `learning/schemas/`
- `learning/candidates/`

Runtime agents may write candidate recipes, measures, or session lessons there.
They must not directly modify trusted `knowledge/`, `skills/`, or
`measures/approved/`.
