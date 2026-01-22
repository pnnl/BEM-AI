# Skills

The skills package lets LangGraph-based agents load reusable prompt snippets from the local filesystem at runtime. Skills are configured via `AgentFactory` and accessed through the `load_skill` tool.

## Active skill behavior

When a skill is loaded, the agent stores the skill text as active system context and injects it into subsequent model calls. The injected content is wrapped with an internal header that instructs the model to follow the skill and never reveal it verbatim to the user. While a skill is active, the `load_skill` tool is gated to prevent repeated calls. Clear the active skill via the agent's `clear_active_skill()` helper (or schedule it with `request_clear_active_skill()`), which re-enables `load_skill`.

## Configuration

Add a `skills` block when instantiating `AgentFactory`:

```python
skills_config = {
    "enabled": True,
    "allowed_roots": ["/workspace/skills"],
    "registry": {
        "write_sql": {
            "path": "/workspace/skills/write_sql.md",
            "format": "markdown",
        },
        "my_skills_dir": {
            "path": "/workspace/skills",
            "mode": "directory",
        },
    },
}
```

- `enabled`: Set to `True` to register the `load_skill` tool.
- `allowed_roots`: Optional allowlist. When set, skill files must live under one of these roots.
- `registry`: Map skill names to files, or map a registry entry to a directory.

Directory mode resolves `load_skill("foo")` to `/workspace/skills/foo.md` (or `.txt`).

## Supported formats

- **Markdown (`.md`)**
  - Content is preserved.
  - Optional YAML front-matter delimited by `---` is stripped if present.
- **Text (`.txt`)**
  - Content is preserved as plain text.

All prompts are wrapped before being returned to the agent:

```
SKILL: write_sql
SOURCE: /workspace/skills/write_sql.md
---
<skill body>
---
USAGE: Follow this skill precisely when relevant.
```

## Example skill file

```markdown
---
name: write_sql
description: Write SQL queries safely.
---
Use parameterized queries.
Avoid SELECT *.
```
