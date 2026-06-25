# OpenStudio AI MCP

This package contains the OpenStudio AI MCP server.

Main surfaces:

- `simulation/`: async, sandboxed, parallel simulation workflow surface.
- `results/`: SQL-backed result retrieval surface.
- `measures/`: MCP-published deterministic measures.
- `tools/`: current model, simulation, results, and SDK-doc tool handlers.
- `runtime/`: workspace, artifact, job, and measure registry support.
- `sdk_docs/`: current SDK documentation lookup implementation.

Imports should use `examples.openstudio_ai.openstudio_mcp`.
