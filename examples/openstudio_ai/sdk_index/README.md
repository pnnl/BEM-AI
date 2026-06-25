# OpenStudio AI SDK Index

This folder is the planned home for the structured SDK index and knowledge
graph layer.

Current SDK documentation lookup still lives under `openstudio_mcp/sdk_docs/`. Future work
should move build and query orchestration here while leaving MCP-facing tool
registration inside `openstudio_mcp/`.

Responsibilities:

- build compact SDK method/class indexes;
- store graph artifacts for class relationships;
- expose query helpers used by MCP tools and host adapters;
- capture SDK lessons that are promoted by the developer learning pipeline.
