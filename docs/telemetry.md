# Agent Telemetry

AUTOMA-AI includes a local-first telemetry facade for agent observability. The
facade emits trace/span/event records for agent turns, messages, tool calls, and
subagent activity. Core AUTOMA-AI does not depend on a collector, cloud service,
or vendor SDK.

Telemetry output is recorder-based. AUTOMA-AI ships simple built-in recorders
and lets projects register their own recorder adapters for OpenTelemetry, AWS
AgentCore, CloudWatch, Datadog, or another backend.

## Built-In Recorders

- `noop`: disabled/default behavior.
- `jsonl`: appends local JSONL records to a file using a background writer
  thread, so async agent execution does not block on each filesystem write.

`Telemetry.flush()` blocks until the selected recorder has persisted or exported
accepted records. Use it in tests, shutdown paths, or debugging scripts that need
to read output immediately after an agent turn.

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
  attributes:
    project.id: demo
  options: {}
  load_plugins: false
```

The same object can be passed to `AgentFactory(..., telemetry_config=...)`.

`content_mode` controls how message and tool payloads are recorded:

- `off` / `metadata`: record payload length and SHA-256 hash only.
- `redacted`: record truncated content with common secret patterns redacted.
- `raw`: record truncated content without redaction. Use only for local debug.

`options` is reserved for recorder-specific configuration. Built-in `jsonl` does
not require it, but custom recorders can read it from `TelemetryConfig.options`.

`load_plugins` controls whether AUTOMA-AI loads recorder factories from installed
package entry points. It defaults to `false` so installed third-party packages
cannot join the telemetry path implicitly.

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

Records have this stable AUTOMA shape before a recorder adapts them:

```json
{"type":"span_start","trace_id":"...","span_id":"...","parent_span_id":null,"name":"agent.turn","kind":"server","attributes":{}}
{"type":"event","trace_id":"...","span_id":"...","name":"message","attributes":{}}
{"type":"span_end","trace_id":"...","span_id":"...","name":"agent.turn","status":"ok","duration_ms":123.4,"attributes":{}}
```

The facade sanitizes attributes before they reach the recorder. Your
`record()` method receives items already redacted according to `content_mode`.
Do not re-derive prompts, tool arguments, metadata, or other payloads from
external state inside a recorder; that bypasses the central redaction policy.

## Custom Recorders

A recorder implements three methods:

```python
from typing import Any


class MyRecorder:
    def record(self, item: dict[str, Any]) -> None:
        ...

    def flush(self) -> None:
        ...

    def close(self) -> None:
        ...
```

Register a factory before the agent is created:

```python
from pathlib import Path
from typing import Any

from automa_ai.config.telemetry import TelemetryConfig
from automa_ai.telemetry import TelemetryRecorder, register_telemetry_recorder


def build_my_recorder(
    config: TelemetryConfig,
    base_attributes: dict[str, Any],
    base_dir: str | Path | None,
) -> TelemetryRecorder:
    return MyRecorder(config.options, base_attributes)


register_telemetry_recorder("my_backend", build_my_recorder)
```

Then use it from YAML or `AgentFactory` config:

```yaml
telemetry:
  enabled: true
  recorder: my_backend
  content_mode: metadata
  service_name: automa-ai
  environment: prod
  options:
    endpoint: https://telemetry.example.com
```

Plugin packages can also expose factories through the
`automa_ai.telemetry_recorders` entry point group. AUTOMA-AI only loads those
entry points when telemetry config sets `load_plugins: true`.

```toml
[project.entry-points."automa_ai.telemetry_recorders"]
my_backend = "my_project.telemetry:build_my_recorder"
```

Unknown enabled recorder names fail fast with a clear error. Disabled telemetry
always uses `noop`.

The built-in recorder names `noop` and `jsonl` are reserved and cannot be
replaced, even with `override=True`. Entry-point plugin loading logs each loaded
recorder and logs a warning for plugins that fail to load or attempt invalid
registration.

## AgentCore Adapter Example

An AWS AgentCore project can integrate by implementing and registering an
`agentcore` recorder outside AUTOMA-AI. That adapter would receive AUTOMA span
and event records, then translate them to the project’s chosen AgentCore
observability path.

A typical AgentCore adapter should handle:

- ADOT/OpenTelemetry runtime setup owned by the deployment, not AUTOMA-AI core.
- W3C/AWS trace propagation such as `traceparent`, `tracestate`, baggage, and
  `X-Amzn-Trace-Id` when those are available at the service boundary.
- AgentCore session correlation, including mapping the runtime session id to a
  stable telemetry attribute or baggage value.
- GenAI semantic convention mapping, for example converting AUTOMA `agent.turn`
  to an agent invocation span and AUTOMA `tool.call` to a tool execution span.
- Backend-specific exporter config, credentials, CloudWatch log group headers,
  sampling, batching, and shutdown behavior.

This keeps AUTOMA-AI portable while still giving AgentCore deployments a stable
extension point.

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
