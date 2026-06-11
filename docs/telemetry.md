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
- `otel`: exports spans through OpenTelemetry. Install the `otel` extra and
  configure an OTLP endpoint, or rely on standard OTEL environment variables.

`Telemetry.flush()` blocks until the selected recorder has persisted or exported
accepted records. Use it in tests, shutdown paths, or debugging scripts that need
to read output immediately after an agent turn.

Telemetry is best-effort and must not break request execution. Recorder failures
from span/event recording, flush, or close are logged and dropped by the facade.
Use `Telemetry.aflush()` and `Telemetry.aclose()` from async shutdown paths so
blocking recorder work runs off the event loop. `A2AAgentServer` calls an
agent's async `aclose()` during normal server teardown, and the LangGraph chat
agent uses that path to `aflush()` accepted telemetry before closing; custom
async hosts should do the same when they own the agent lifecycle.

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
not require it. Built-in `otel` supports `exporter`, `endpoint`, `headers`,
`timeout`, `processor`, `resource_attributes`, `flush_timeout_millis`,
`flush_on_close`, and `shutdown_on_close`. Custom recorders can read their own
settings from `TelemetryConfig.options`.

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

## OpenTelemetry Recorder

Install the OTEL extra before enabling the built-in OpenTelemetry recorder:

```bash
pip install "automa_ai[otel]"
```

Basic OTLP-over-HTTP configuration:

```yaml
telemetry:
  enabled: true
  recorder: otel
  content_mode: metadata
  service_name: automa-ai
  environment: prod
  options:
    exporter: otlp_http
    endpoint: https://collector.example.com/v1/traces
    processor: batch
    flush_timeout_millis: 5000
```

For Langfuse, use Langfuse as the OTLP destination:

```yaml
telemetry:
  enabled: true
  recorder: otel
  content_mode: metadata
  service_name: automa-ai
  environment: prod
  options:
    exporter: otlp_http
    endpoint: https://cloud.langfuse.com/api/public/otel
    headers:
      Authorization: Basic <base64-public-key-colon-secret-key>
      x-langfuse-ingestion-version: "4"
```

The recorder uses AUTOMA trace and span ids as the exported OpenTelemetry span
context ids. AUTOMA trace ids are 128-bit OTEL trace ids, and AUTOMA span ids
are 64-bit OTEL span ids. This lets A2A-propagated telemetry metadata preserve
parent-child relationships across process boundaries. The same values are also
kept as `automa.trace_id`, `automa.span_id`, and `automa.parent_span_id`
attributes for backend queries.

The recorder adds a small GenAI semantic convention mapping:

- `agent.turn` spans export as `gen_ai.operation.name=invoke_agent`.
- `tool.call` spans export as `gen_ai.operation.name=execute_tool`.
- Available `agent.*`, `tool.*`, and `model.*` attributes are copied into
  matching `gen_ai.*` attributes.
- User `message` events are also promoted to the active span as `input.value`
  and `gen_ai.prompt`; assistant `message` events are promoted as
  `output.value` and `gen_ai.completion`. The original events are still
  exported.
- `tool.input` and `tool.output` events are promoted to their tool span as
  `input.value` and `output.value`, while preserving the original events.
- LangChain chat model calls are recorded through a per-turn callback as
  `llm.call` spans. The OTEL encoder exports these as GenAI client spans with
  `gen_ai.operation.name=chat`, `gen_ai.request.model`, `gen_ai.provider.name`,
  `gen_ai.prompt`, `input.value`, and span kind `CLIENT`.
- LLM responses emit `llm.output` events that are promoted to the active LLM
  span as `output.value`, `gen_ai.completion`, `gen_ai.response.model`, and
  `gen_ai.response.finish_reasons`.
- Final LangChain message `usage_metadata` and `response_metadata` are emitted
  as `model.usage` events when providers expose token, model, and provider
  fields. Token usage is exported with both AUTOMA names such as
  `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens` and
  prompt/completion aliases used by span-oriented LLM backends.

This recorder does not synthesize cost, embedding spans, retrieval spans, or
provider HTTP spans. It promotes already-recorded AUTOMA events onto spans so
backends such as Langfuse or AgentCore can populate trace preview and usage
fields.

`otel` uses synchronous OpenTelemetry SDK exporters under the hood. `flush()`
calls `force_flush(timeout_millis=...)`; the default timeout is `5000` ms.
`close()` ends any open spans but does not force-flush or call provider shutdown
by default, because provider shutdown can block on batch export during worker
recycling or request teardown. Set `flush_on_close: true` or
`shutdown_on_close: true` only in lifecycle code where that blocking behavior is
acceptable, and prefer `Telemetry.aclose()` in async applications.

Do not move OTEL `record()` calls behind a background queue or worker thread.
The recorder intentionally runs synchronously in the caller's thread/task so
`context.attach(trace.set_span_in_context(...))` attaches the AUTOMA span to the
same OpenTelemetry context that auto-instrumented libraries such as `httpx`,
`requests`, `botocore`, and model SDKs read from. If span start/end recording
happens in a different worker context than the tool/model call, those
auto-instrumented child spans will not inherit the AUTOMA `agent.turn` or
`tool.call` parent span. Concurrent tool calls are supported when each span
starts, runs, and ends inside its own asyncio task/thread context; do not start a
span in one task and end it in another.

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
