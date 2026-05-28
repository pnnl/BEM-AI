# Agent Telemetry

AUTOMA-AI includes a local-first telemetry facade for agent observability. The
facade uses trace/span/event concepts that map cleanly to OpenTelemetry.
The default implementation does not require an external collector, backend,
or AWS service, while the `otel` recorder can export to an OTLP collector
for AWS AgentCore observability.

## Current recorders

- `noop`: disabled/default behavior.
- `jsonl`: appends local JSONL records to a file using a background writer
  thread, so async agent execution does not block on each filesystem write.
- `otel`: exports spans and events through OpenTelemetry OTLP gRPC for AWS
  AgentCore observability or any compatible collector.

`Telemetry.flush()` blocks until the selected recorder has persisted or exported
accepted records. Use it in tests, shutdown paths, or debugging scripts that need
to read the file immediately after an agent turn.

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

For AWS AgentCore observability, use the OpenTelemetry recorder and configure the
standard OTLP exporter environment expected by your deployment target:

```yaml
telemetry:
  enabled: true
  recorder: otel
  content_mode: metadata
  service_name: automa-ai
  environment: agentcore
```

Common OpenTelemetry environment variables include `OTEL_EXPORTER_OTLP_ENDPOINT`,
`OTEL_EXPORTER_OTLP_HEADERS`, and `OTEL_SERVICE_NAME`.

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

## Tool Wrapping Behavior

When telemetry is enabled, AUTOMA-AI wraps LangChain tool objects so each tool
call can emit a `tool.call` span plus `tool.input` and `tool.output` events. The
wrapper must not change tool behavior. It forwards the original LangChain
`RunnableConfig` to the wrapped tool so callbacks, tags, metadata, and
config-injected behavior continue to work.

The wrapper also preserves execution-affecting fields from the original tool:

- `return_direct`
- `handle_tool_error`
- `handle_validation_error`
- `verbose`
- `callbacks`
- `tags`
- `metadata`

`response_format` is handled slightly differently. The wrapper delegates to the
original tool's `ainvoke()`, so the original tool still enforces its own
`response_format`, including `content_and_artifact`. The telemetry wrapper
itself uses `response_format: content` to avoid applying LangChain's raw
`(content, artifact)` tuple validation a second time to an already processed
tool result.

Most built-in AUTOMA-AI tools use default values for these fields today.
However, these fields are part of LangChain's public tool surface and can be
present on tools supplied by MCP adapters, direct LangChain integrations, or
future custom tool builders. Telemetry code should preserve them because a tool
with `return_direct=true` or custom error handling can change agent control flow
if those settings are dropped.

Future work: decide whether AUTOMA-AI should expose selected LangChain tool
execution options, such as `return_direct`, `tags`, `metadata`, and custom error
handling, through first-class tool configuration. Telemetry already preserves
these fields when they are present, but most AUTOMA-AI tool config paths do not
currently let users set them directly.

Records are OpenTelemetry-shaped:

```json
{"type":"span_start","trace_id":"...","span_id":"...","parent_span_id":null,"name":"agent.turn","kind":"server","attributes":{}}
{"type":"event","trace_id":"...","span_id":"...","name":"message","attributes":{}}
{"type":"span_end","trace_id":"...","span_id":"...","name":"agent.turn","status":"ok","duration_ms":123.4,"attributes":{}}
```

## AWS AgentCore Direction

AWS AgentCore observability uses OpenTelemetry-compatible telemetry. AUTOMA-AI
keeps telemetry calls behind a small facade so local development can use JSONL
while AgentCore deployments can use the `otel` recorder to export the same
span/event model to ADOT/CloudWatch through OTLP.

Do not put secrets or raw user data into trace propagation metadata. The A2A
metadata only carries IDs needed to connect spans across local and remote
agents.
