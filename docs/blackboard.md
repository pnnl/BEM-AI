# Shared Session Blackboard

## What it is

The Shared Session Blackboard is a **session-scoped**, structured document used by orchestrators and subagents to coordinate long-running workflows.

It is:
- Shared state for one session (`session_id`).
- Explicitly schema-driven and versioned.
- Edited only through deterministic tools.
- Persisted via pluggable backends.

It is not:
- Agent semantic memory.
- Embedding/vector retrieval.
- Cross-session/global storage.

## Document model

A blackboard document contains:
- `session_id`
- `schema_name`
- `schema_version`
- `revision` (optimistic concurrency)
- `updated_at`
- `data` (schema validated)
- `events` (append-only audit trail)

## Schema definition

Use JSON Schema in `BlackboardConfig.schema`.

Example CE schema:

```python
{
  "type": "object",
  "properties": {
    "project": {
      "type": "object",
      "properties": {
        "description": {
          "type": "object",
          "properties": {
            "confirmed_text": {"type": "string"}
          }
        }
      }
    },
    "recommended_ces": {"type": "array", "items": {"type": "string"}},
    "location": {"type": "string"},
    "resources": {"type": "array", "items": {"type": "string"}}
  },
  "required": ["project", "recommended_ces"]
}
```

## Configuration

`AgentFactory` accepts `blackboard_config`.

### Local JSON (default)

```python
blackboard_config = {
    "enabled": True,
    "backend": "local_json",
    "base_dir": ".blackboard",
    "schema_name": "ce_workflow",
    "schema_version": "1.0",
    "schema": {...},
    "initial_data": {"project": {"description": {"confirmed_text": ""}}, "recommended_ces": []},
}
```

### S3 (example adapter)

```python
blackboard_config = {
    "enabled": True,
    "backend": "s3_json",
    "s3_bucket": "my-blackboard-bucket",
    "s3_prefix": "sessions",
    "schema_name": "ce_workflow",
    "schema_version": "1.0",
    "schema": {...},
}
```

### DynamoDB (example adapter)

```python
blackboard_config = {
    "enabled": True,
    "backend": "dynamodb_json",
    "dynamodb_table": "blackboard_sessions",
    "schema_name": "ce_workflow",
    "schema_version": "1.0",
    "schema": {...},
}
```

## Lifecycle and `get_or_create` behavior

`GenericLangGraphChatAgent` calls `blackboard_store.get_or_create(...)` on each `invoke` and `stream` call.

This means:
- If the session document does not exist yet, a new document is created using `initial_data`.
- If the session document already exists, the existing document is loaded and reused.
- `initial_data` is **not** re-applied to existing documents.

This preserves session continuity across multiple turns while still providing deterministic bootstrapping for new sessions.

## Validation behavior when `jsonschema` is unavailable

The blackboard validator uses `jsonschema` when installed.
If `jsonschema` is missing, validation falls back to a lightweight built-in validator that enforces only a subset of JSON Schema (primarily `type`, nested `properties` traversal, and `required`).

For production use, install `jsonschema` to enforce the full schema surface (such as `additionalProperties`, string/number bounds, regex patterns, and other advanced keywords).

## Agent tools

When enabled, agent tool registry includes:
- `blackboard_read(session_id, path=None)`
- `blackboard_write(session_id, ops, expected_revision=None, actor=None, note=None)`
- `blackboard_get_revision(session_id)`

Supported write ops:
- `set`
- `merge`
- `append`
- `remove`

Path syntax: dotted keys plus list indexes, e.g. `project.sections[0].title`.

## Contract injection

When blackboard is enabled, `AgentFactory` builds a “Shared Session Blackboard Contract” from schema metadata and injects it into:
- The orchestrator/system prompt.
- Subagent delegation payloads.

This keeps all participating agents aligned on shared-state behavior.

## Blackboard lifecycle and `initial_data`

The agent runtime calls an internal `_ensure_blackboard` helper on every `invoke`/`stream` call. This helper uses a `get_or_create` operation against the configured backend:

- If a blackboard document already exists for the given `session_id`, that existing document is **loaded and reused**.
- If no document exists yet for that `session_id`, a new document is created using the configured schema and **`initial_data`**.

As a result:

- `initial_data` is applied **only once**, when the blackboard is created for a session that does not yet have one.
- Subsequent calls for the same `session_id` will always load the existing blackboard and will **not** re-apply or merge `initial_data`.
- Changing `initial_data` in configuration after a session has already started will not affect that session’s existing blackboard document.

Design your workflows and migrations with this in mind—for example, use schema versioning and explicit write operations (via `blackboard_write`) to evolve existing session documents rather than relying on changes to `initial_data`.
