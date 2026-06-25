# OpenStudio AI Harness

The harness is the host-agnostic package boundary for OpenStudio AI. It collects
the assets needed by an agent host:

- MCP server entrypoint;
- prompt contracts;
- skill files;
- knowledge base roots;
- SDK index roots;
- blackboard schema;
- learning-event log path.

Host-specific details belong in `adapters/`. The harness should remain portable
across Codex, Claude Code, and future agent shells.

