# OpenStudio AI Agent Adapters

This folder defines the host-specific adapter layer for packaging OpenStudio AI
into agent shells such as Codex or Claude Code.

Adapters are responsible for:

- loading the harness system prompt and prompt contracts;
- exposing the skill directory to the host agent;
- connecting the OpenStudio MCP server;
- wiring the blackboard state store;
- recording learning events from host-agent activity.

Adapters should stay thin. Product behavior belongs in `harness/`,
`blackboard/`, `learning/`, `skills/`, and `openstudio_mcp/`.

## Claude Code Plugin Export

Export a Claude plugin-style package:

```bash
.venv/bin/python -m examples.openstudio_ai.adapters.claude_code_adapter export-plugin \
  --output-dir /tmp/openstudio-ai-plugin
```

Preview package files without writing:

```bash
.venv/bin/python -m examples.openstudio_ai.adapters.claude_code_adapter export-plugin \
  --output-dir /tmp/openstudio-ai-plugin \
  --dry-run
```

The exported package has this shape:

```text
openstudio-ai/
├── .claude-plugin/plugin.json
├── .mcp.json
├── README.md
├── CONNECTORS.md
├── commands/
├── skills/
├── knowledge/
├── instructions/
└── blackboard/schemas/
```

Skills and knowledge are exported as separate files and folders. They are not
flattened into one large `CLAUDE.md`.

## Claude Code Project Install

Preview the files that would be installed into a Claude Code project:

```bash
.venv/bin/python -m examples.openstudio_ai.adapters.claude_code_adapter install \
  --target-dir /path/to/claude/project \
  --dry-run
```

Install into a Claude Code project:

```bash
.venv/bin/python -m examples.openstudio_ai.adapters.claude_code_adapter install \
  --target-dir /path/to/claude/project
```

The installer writes:

- `.mcp.json`
  Project-scoped MCP server registration for `openstudio_ai`.
- `.claude/CLAUDE.md`
  Project instructions containing OpenStudio AI harness paths, prompt
  contracts, and runtime skill references.

If `.claude/CLAUDE.md` already exists and is not managed by OpenStudio AI, the
installer stops unless `--force` is provided. With `--force`, it appends a
generated OpenStudio AI block.

Project install is mainly useful for local development and debugging. The
plugin export command is the intended distributable path.
