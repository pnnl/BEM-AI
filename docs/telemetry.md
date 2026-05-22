# Agent Telemetry

AUTOMA-AI includes a local-first telemetry facade for agent observability. The
facade uses trace/span/event concepts that map cleanly to OpenTelemetry later,
but the default implementation does not require an external collector, backend,
or AWS service.

## Current recorders

- `noop`: disabled/default behavior.
- `jsonl`: appends local JSONL records to a file.
- `otel`: reserved for optional OpenTelemetry and AWS AgentCore integration.
  It is intentionally not bundled into the local-first MVP.

## Configuration

```yaml
telemetry:
  enabled: true
  recorder: jsonl
  path: ./logs/telemetry.jsonl
  content_mode: metadata
  max_content_chars: 4000
  service_name: automa-ai
  environment: local
```

The same object can be passed to `AgentFactory(..., telemetry_config=...)`.

`content_mode` controls how message and tool payloads are recorded:

- `off` / `metadata`: record payload length and SHA-256 hash only.
- `redacted`: record truncated content with common secret patterns redacted.
- `raw`: record truncated content without redaction. Use only for local debug.

## What Is Captured

For `LANGGRAPHCHAT` agents, telemetry captures:

- `agent.turn` spans for `invoke` and `stream` calls.
- user and assistant message events.
- tool-call request and tool-result events.
- wrapped LangChain tool spans for binding tools, MCP tools, subagent tools,
  blackboard tools, and skill tools.
- subagent stream events.
- trace context propagation through A2A metadata using
  `telemetry_trace_id` and `telemetry_parent_span_id`.

Records are OpenTelemetry-shaped:

```json
{"type":"span_start","trace_id":"...","span_id":"...","parent_span_id":null,"name":"agent.turn","kind":"server","attributes":{}}
{"type":"event","trace_id":"...","span_id":"...","name":"message","attributes":{}}
{"type":"span_end","trace_id":"...","span_id":"...","name":"agent.turn","status":"ok","duration_ms":123.4,"attributes":{}}
```

## AWS AgentCore Direction

AWS AgentCore observability uses OpenTelemetry-compatible telemetry. AUTOMA-AI
keeps telemetry calls behind a small facade so local development can use JSONL
while AgentCore deployments can later install an optional `otel` recorder that
exports the same span/event model to ADOT/CloudWatch.

Do not put secrets or raw user data into trace propagation metadata. The A2A
metadata only carries IDs needed to connect spans across local and remote
agents.
