# Developer Learning Agent

This folder defines the agent-assisted curation workflow for OpenStudio AI
developer learning.

The current runner is deterministic:

```bash
.venv/bin/python -m examples.openstudio_ai.learning.developer_pipeline.run_pipeline
```

It reads raw logs, reflects them into candidate lessons, and writes reviewable
JSON files under `learning/review_queue/`.

The intended agent loop is:

```text
capture -> reflect -> propose candidate -> human review -> eval validation -> promote
```

The agent must not directly edit trusted assets such as `knowledge/`,
`skills/*.md`, `skills/specs/*.yaml`, `measures/approved/`, or MCP tools.
