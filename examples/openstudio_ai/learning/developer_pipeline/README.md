# Developer Learning Pipeline

The developer pipeline turns raw AI/modeling experience into trusted OpenStudio
AI assets.

Stages:

1. Capture raw traces, warnings, failures, user corrections, and review notes.
2. Distill raw records into candidate lessons, skills, evals, or measures.
3. Review with a human/modeler gate.
4. Validate by adding or updating eval cases.
5. Promote approved assets into the trusted knowledge base, skill library, SDK
   index, MCP tools, or measure registry.

Trusted assets should only change through this pipeline.

## Deterministic Runner

```bash
.venv/bin/python -m examples.openstudio_ai.learning.developer_pipeline.run_pipeline
```

The runner scans OpenStudio AI logs and writes candidate lesson JSON files to
`learning/review_queue/`. It is deterministic so it can be tested and reviewed;
the `developer_agent/` folder defines the agent-assisted version of the same
workflow.
