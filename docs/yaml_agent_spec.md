# YAML Agent Spec

The YAML agent spec lets one YAML file define one AUTOMA-AI agent and boot it as
an A2A server with a small Python bootstrap. It is a thin declarative layer over
the existing `AgentFactory` and `A2AAgentServer` APIs.

This feature is intentionally single-agent scoped. If an application needs more
than one agent server, load each YAML file explicitly in Python and register each
server with `A2AServerManager`.

## Quick Start

Create `agent.yaml`:

```yaml
spec_version: v1

agent_card:
  name: Demo Agent
  description: A YAML-defined AUTOMA-AI agent.
  version: 0.1.0
  defaultInputModes: [text]
  defaultOutputModes: [text]
  capabilities:
    streaming: true
  supportedInterfaces:
    - url: http://localhost:30000
      protocolBinding: JSONRPC
      protocolVersion: "1.0"

instructions:
  text: |
    You are a concise assistant.
    Answer with direct, factual responses.

model:
  provider: ollama
  name: llama3.1:8b

runtime:
  agent_type: langgraph-chat
  debug: false

memory:
  short_term_limit: 10
  short_term_max: 30
  long_term_strategy: summarize
  stores:
    - name: default_sqlite
      memory_type: short_term
      store_config:
        db_path: ./short_term_memory.sqlite
    - name: default_chroma
      memory_type: long_term
      store_config:
        db_path: ./long_term_chroma
```

Create `run_agent.py`:

```python
import asyncio

from automa_ai.common.agent_registry import A2AServerManager
from automa_ai.config.agent_spec import load_a2a_server_from_yaml


async def main() -> None:
    server = load_a2a_server_from_yaml("agent.yaml")

    manager = A2AServerManager()
    manager.add_server(server)
    await manager.start_all()

    print("A2A server started. Press Ctrl+C to stop.")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
```

Run it:

```bash
python run_agent.py
```

The A2A server host and port come from
`agent_card.supportedInterfaces[0].url`.

## API Shape

Use `load_a2a_server_from_yaml(...)` when the YAML file should become a bootable
A2A server:

```python
from automa_ai.config.agent_spec import load_a2a_server_from_yaml

server = load_a2a_server_from_yaml("agent.yaml")
```

Use `load_agent_factory_from_yaml(...)` when the YAML file should become an
`AgentFactory`:

```python
from automa_ai.config.agent_spec import load_agent_factory_from_yaml

factory = load_agent_factory_from_yaml("agent.yaml")
agent = factory.get_agent()
```

For ephemeral headless subagents created by the `yaml_agent` tool, start from
`docs/templates/headless_subagent.yaml`. These subagent specs should stay small:
use default runtime settings, enable only built-in default tools such as
`web_search` or `run_python` when needed, omit MCP and persistent memory
configuration, and do not define nested subagents.

For validation, inspection, or programmatic edits before building, load the
intermediate spec explicitly:

```python
from automa_ai.config.agent_spec import YamlAgentSpec, load_a2a_server_from_yaml

spec = YamlAgentSpec.from_yaml_file("agent.yaml")
print(spec.agent_card["name"])

server = load_a2a_server_from_yaml(spec)
```

Both builder helpers accept either a YAML path or an existing `YamlAgentSpec`.

## Instruction Files

Instructions can be written inline or stored in a separate file.

Inline:

```yaml
instructions:
  text: |
    You are an OpenStudio sizing assistant.
    Ask for missing model and weather inputs before running tools.
```

File-backed:

```yaml
instructions:
  path: ./prompts/openstudio_agent.md
```

Relative instruction paths are resolved relative to the YAML file, not the
current shell directory.

## Full Example

```yaml
spec_version: v1

agent_card:
  name: OpenStudio MCP Sizing Agent
  description: AgentFactory-based agent wired to OpenStudio MCP tools.
  version: 0.1.0
  defaultInputModes: [text]
  defaultOutputModes: [text]
  capabilities:
    streaming: true
    pushNotifications: false
  supportedInterfaces:
    - url: http://localhost:9999
      protocolBinding: JSONRPC
      protocolVersion: "1.0"
  skills:
    - id: hvac_sizing_assistant
      name: OpenStudio HVAC Sizing Assistant
      description: Runs a constrained OpenStudio sizing workflow through MCP tools.
      tags: [openstudio, mcp, hvac_sizing]
      examples:
        - Run a sizing workflow for model file:///tmp/demo.osm.

instructions:
  path: ./prompts/openstudio_agent.md

model:
  provider: ollama
  name: llama3.1:8b
  base_url: http://localhost:11434
  max_retries: 2

runtime:
  agent_type: langgraph-chat
  transient_retry_attempts: 1
  debug: true

server:
  log_dir: ./logs
  base_url_path: null
  health_check_path: /health

mcp:
  servers:
    openstudio_mcp:
      name: openstudio_mcp
      host: localhost
      port: 10210
      transport: sse
      timeout: 30
      sse_read_timeout: 300

tools:
  tools:
    - type: my_project.tools.search_building_codes
      config:
        top_k: 5
    - type: web_search
      config:
        provider: opensource

skills:
  enabled: true
  allowed_roots:
    - ./skills
  registry:
    hvac_sizing:
      path: ./skills/hvac_sizing.md

memory:
  short_term_limit: 10
  short_term_max: 30
  long_term_strategy: summarize
  stores:
    - name: default_sqlite
      memory_type: short_term
      store_config:
        db_path: ./short_term_memory.sqlite
    - name: default_chroma
      memory_type: long_term
      store_config:
        db_path: ./long_term_chroma

checkpointer:
  type: redis_plain
  redis_url: redis://localhost:6379
  checkpoint_ttl_seconds: 21600
  max_checkpoints_per_thread: 15
  refresh_ttl_on_read: true
  socket_timeout: 5.0
  socket_connect_timeout: 5.0
  health_check_interval: 30
  retry_on_timeout: true

telemetry:
  enabled: true
  recorder: jsonl
  path: ./logs/telemetry.jsonl
  content_mode: metadata
  max_content_chars: 4000
  load_plugins: false

budget:
  max_input_tokens: 12000
  reserve_output_tokens: 1200
  max_output_tokens: 1000
  max_model_calls_per_turn: 6
  max_tool_calls_per_turn: 10
  max_session_tokens: 100000
  store:
    backend: sqlite
    db_path: ./token_usage.db
```

## Parameter Reference

### `spec_version`

Required string. Currently only `v1` is supported.

### `agent_card`

Required object. This is the public A2A 1.0 agent card, passed as a plain
dictionary into the runtime.

Required fields:

- `name`: Display name of the agent.
- `description`: Short description of what the agent does.
- `supportedInterfaces`: List of A2A interfaces. The first entry must include
  `url`; `A2AAgentServer` uses this URL to derive host, port, and optional base
  path.

Recommended fields:

- `version`: Agent version string.
- `defaultInputModes`: Usually `[text]`.
- `defaultOutputModes`: Usually `[text]`.
- `capabilities.streaming`: Set to `true` for streaming-capable agents.
- `capabilities.pushNotifications`: Set when push notifications are supported.
- `skills`: A2A skill metadata exposed on the card.

Do not use the old A2A card shape with top-level `url`. Use
`supportedInterfaces` instead.

### `instructions`

Required object. Exactly one source must be provided.

- `text`: Inline system instructions.
- `path`: Path to a text or Markdown instruction file. Relative paths are
  resolved from the YAML file's directory.

The resolved instruction text is passed to `AgentFactory(..., instructions=...)`.

### `model`

Required object.

- `provider`: LLM provider enum value. Supported values come from `GenericLLM`:
  `openai`, `ollama`, `claude`, `gemini`, `litellm`, `bedrock`.
- `name`: Model name or deployment name passed to the provider.
- `base_url`: Optional provider base URL.
- `api_key`: Optional API key. Prefer environment variables for secrets.
- `api_version`: Optional API version, commonly needed for Azure OpenAI.
- `max_retries`: Optional model retry count for providers that support it.

### `runtime`

Optional object.

- `agent_type`: Agent implementation. Defaults to `langgraph-chat`. New YAML
  specs should normally use `langgraph-chat`.
- `transient_retry_attempts`: Number of transient agent retry attempts. Defaults
  to `0`.
- `debug`: Enables debug behavior in the underlying agent. Defaults to `false`.

### `server`

Optional object for the `A2AAgentServer` wrapper.

- `log_dir`: Log directory. Defaults to `./logs`.
- `base_url_path`: Optional mount path override. If omitted, the path from
  `agent_card.supportedInterfaces[0].url` is used. If provided, the server
  mounts the A2A routes at this path and advertises the same path in the
  returned agent card.
- `health_check_path`: Health endpoint path. Defaults to `/health`.

The server host and port are not configured here. They come from the agent card's
primary supported interface URL.

### `mcp`

Optional object for MCP tool connections used by the agent.

```yaml
mcp:
  servers:
    alias:
      name: actual_server_name
      host: localhost
      port: 10210
      transport: sse
```

Each server entry supports:

- `name`: MCP server name.
- `host`: MCP server host.
- `port`: MCP server port.
- `transport`: `stdio`, `sse`, or `streamable-http`.
- `timeout`: Optional client timeout.
- `sse_read_timeout`: Optional SSE read timeout.
- `agent_cards_dir`: Optional agent-card directory for the special agent-card
  MCP server.

YAML MCP entries configure client connections for the agent. They do not launch
MCP server processes. Start MCP servers separately with `MCPServerManager`.

### `subagents`

Optional list. Each entry becomes a `SubAgentSpec` and exposes a delegation tool
to the coordinator agent. Each entry must provide exactly one card source:

- `spec_path`: Path to another YAML agent spec. The loader reads that spec's
  `agent_card`.
- `card_path`: Path to a standalone JSON agent card.
- `agent_card`: Inline A2A 1.0 agent card.

Relative `spec_path` and `card_path` values are resolved from the current YAML
file's directory.

Preferred form when each subagent already has its own YAML spec:

```yaml
subagents:
  - spec_path: ./flight_agent.yaml
  - spec_path: ./hotel_agent.yaml
  - spec_path: ./car_agent.yaml
```

Use `card_path` when agent cards are maintained as JSON fixtures:

```yaml
subagents:
  - card_path: ../agents/flight_card.json
  - card_path: ../agents/hotel_card.json
```

Use inline `agent_card` for small examples or dynamically authored specs:

```yaml
subagents:
  - agent_card:
      name: Math Agent
      description: Handles arithmetic.
      version: 0.1.0
      defaultInputModes: [text]
      defaultOutputModes: [text]
      capabilities:
        streaming: true
      supportedInterfaces:
        - url: http://localhost:31000
          protocolBinding: JSONRPC
          protocolVersion: "1.0"
```

For all forms, `name` and `description` default from the resolved card. You can
override either field at the subagent entry level to control the generated tool
name or delegation description:

```yaml
subagents:
  - name: calculator
    description: Use for deterministic arithmetic only.
    spec_path: ./math_agent.yaml
```

Resolved subagent cards must use the A2A 1.0 `supportedInterfaces` shape. The
loader validates cards loaded from `spec_path`, `card_path`, and inline
`agent_card` entries before creating runtime `SubAgentSpec` objects.

### `tools`

Optional object or list passed through to `AgentFactory(..., tools_config=...)`.
The YAML loader only rebases path fields it can identify safely. Today that
means the built-in `run_python` tool's `config.workspace_root` and
`config.failure_experience_path` are resolved from the YAML file's directory.
Other tool config strings are passed through as-is.
For local `@tool` functions, set `type` to the fully qualified dotted function
path. The tool registry imports the module from that path before building the
tool, which also works when A2A servers construct agents in child processes.

Object form:

```yaml
tools:
  tools:
    - type: my_project.tools.search_building_codes
      config:
        top_k: 5
    - type: web_search
      config:
        provider: opensource
```

List form:

```yaml
tools:
  - type: run_python
    config:
      workspace_root: .
      warn_script_lines: 120
      failure_experience_path: ./logs/python_script_failure_experience.jsonl
```

### `skills`

Optional object passed through to `AgentFactory(..., skills_config=...)`.
Relative `allowed_roots` and registry `path` values are resolved from the YAML
file's directory before they are passed to `SkillManager`.

```yaml
skills:
  enabled: true
  allowed_roots:
    - ./skills
  registry:
    sizing:
      path: ./skills/sizing.md
```

### `retriever`

Optional object passed through to `AgentFactory(..., retriever_spec=...)`.

```yaml
retriever:
  enabled: true
  provider: chroma
  top_k: 4
  embedding:
    provider: ollama
    model: mxbai-embed-large
  retrieval_provider_config:
    collection_name: docs
```

### `memory`

Optional object passed through to `AgentFactory(..., memory_config=...)`.

The built-in memory store entry points include `default_sqlite` for SQLite and
`default_chroma` for ChromaDB. Use SQLite for short-term memory and ChromaDB for
long-term memory:

```yaml
memory:
  short_term_limit: 10
  short_term_max: 30
  long_term_strategy: summarize
  stores:
    - name: default_sqlite
      memory_type: short_term
      store_config:
        db_path: ./short_term_memory.sqlite
    - name: default_chroma
      memory_type: long_term
      store_config:
        db_path: ./long_term_chroma
```

Relative `store_config.db_path` values are resolved from the YAML file's
directory. Custom memory stores can be registered through the
`automa_ai.memory_stores` entry point group and referenced by `name`.

### `blackboard`

Optional object passed through to `AgentFactory(..., blackboard_config=...)`.
For local JSON blackboards, relative `store.base_dir` values are resolved from
the YAML file's directory.

```yaml
blackboard:
  enabled: true
  store:
    backend: local_json
    base_dir: ./.blackboards
  schema_name: task
  schema_version: v1
  schema:
    type: object
    additionalProperties: true
  initial_data: {}
```

### `checkpointer`

Optional object or string passed through to
`AgentFactory(..., checkpointer_config=...)`.

```yaml
checkpointer:
  type: default
```

Redis examples:

```yaml
checkpointer:
  type: redis_plain
  redis_url: redis://localhost:6379
  # redis_plain does not support ElastiCache cluster mode enabled.
  # Use a single-shard Redis/Valkey target, such as cluster mode disabled
  # with replicas.
  checkpoint_ttl_seconds: 21600
  max_checkpoints_per_thread: 15
  refresh_ttl_on_read: true
  socket_timeout: 5.0
  socket_connect_timeout: 5.0
  health_check_interval: 30
  retry_on_timeout: true
```

`redis_plain` uses Redis as a bounded hot-session cache. The supported
plain-Redis-only fields are:

- `checkpoint_ttl_seconds`: Idle TTL applied to checkpoint keys. Defaults to
  `21600` seconds.
- `max_checkpoints_per_thread`: Resume-friendly retention cap counted by
  distinct LangGraph `metadata["step"]` groups. Defaults to `15`. This is not a
  strict byte or raw checkpoint-record cap.
- `refresh_ttl_on_read`: Refresh checkpoint TTLs during reads and list calls.
  Defaults to `true`.
- `socket_timeout`: Redis socket read/write timeout in seconds. Defaults to
  `5.0`.
- `socket_connect_timeout`: Redis connection timeout in seconds. Defaults to
  `5.0`.
- `health_check_interval`: Redis connection-pool health check interval in
  seconds. Defaults to `30`.
- `retry_on_timeout`: Ask redis-py to retry timeout errors. Defaults to `true`.

For ElastiCache with in-transit encryption, use `rediss://...`. Keep AUTH
tokens in deployment secrets rather than committed YAML. Advanced TLS CA or IAM
auth flows should use a prebuilt Redis client in application code instead of
only `redis_url`.

`redis_plain` does not support Redis Cluster mode or ElastiCache cluster mode
enabled. It touches multiple keys while expiring, pruning, and deleting a
thread's checkpoints. Without Redis hash tags those keys can be assigned to
different hash slots and raise `CROSSSLOT` errors. Deploy it on a single-shard
Redis/Valkey target, such as ElastiCache cluster mode disabled with replicas.

### `budget`

Optional object passed through to `AgentFactory(..., budget_config=...)`.

Token budgeting is enforced with LangChain agent middleware before and after
model calls:

- `max_input_tokens`: Approximate maximum input tokens allowed for one model
  call. Conversation messages are quietly trimmed before the call when needed.
  If the system prompt alone leaves no room for messages, the agent returns a
  token-budget error instead of calling the model.
- `reserve_output_tokens`: Tokens held back from `max_input_tokens` for the
  model response.
- `max_output_tokens`: Output-token cap passed into the model call through
  `model_settings`. The default key is `max_tokens`.
- `max_model_calls_per_turn`: Maximum model calls allowed during one agent run.
- `max_tool_calls_per_turn`: Maximum tool calls allowed during one agent run.
- `max_session_tokens`: Maximum persisted total tokens for one AUTOMA context.
- `session_token_window`: Optional time window for `max_session_tokens`.
- `max_user_tokens`: Maximum persisted total tokens for one user.
- `user_token_window`: Optional time window for `max_user_tokens`.
- `summarize_when_tokens`: Enables LangChain summarization middleware when the
  message history reaches this approximate token count.
- `keep_recent_messages`: Number of recent messages kept by summarization.
- `store`: Optional token-usage persistence backend. `sqlite` is built in.
  Custom backends can be registered with `register_token_usage_store(...)` or
  exposed through the `automa_ai.token_usage_stores` package entry point group.
  Backend-specific fields are passed through to the selected store.

```yaml
budget:
  max_input_tokens: 12000
  reserve_output_tokens: 1200
  max_output_tokens: 1000
  max_model_calls_per_turn: 6
  max_tool_calls_per_turn: 10
  max_session_tokens: 100000
  session_token_window:
    period: calendar_day
    timezone: America/Los_Angeles
  max_user_tokens: 500000
  user_token_window:
    period: calendar_month
    timezone: America/Los_Angeles
  summarize_when_tokens: 10000
  keep_recent_messages: 20
  store:
    backend: sqlite
    db_path: ./token_usage.db
```

Custom token usage store packages can expose a `TokenUsageStore` subclass under
the backend name used in YAML:

```toml
[project.entry-points."automa_ai.token_usage_stores"]
dynamodb = "my_package.token_usage:DynamoDBTokenUsageStore"
```

```yaml
budget:
  max_session_tokens: 100000
  store:
    backend: dynamodb
    table_name: automa-token-usage
    region_name: us-west-2
```

Token windows are append-only filters over the usage ledger; usage rows are not
deleted or reset. Supported `period` values are:

- `lifetime`: Default behavior. Count all persisted usage for the scope.
- `calendar_day`: Count usage from the current local day in `timezone`.
- `calendar_month`: Count usage from the current local month in `timezone`.
- `rolling`: Count usage from the last `rolling_seconds`.

`timezone` must be an IANA timezone name, such as `UTC`,
`America/Los_Angeles`, or `Europe/London`.

```yaml
budget:
  max_session_tokens: 100000
  session_token_window:
    period: calendar_day
    timezone: UTC
  max_user_tokens: 500000
  user_token_window:
    period: rolling
    rolling_seconds: 2592000
    timezone: UTC
```

### `telemetry`

Optional object or string passed through to
`AgentFactory(..., telemetry_config=...)`.

Local JSONL telemetry records trace/span/event shaped data without requiring an
external collector. Projects can also register custom telemetry recorders and
refer to them by name in `recorder`:

```yaml
telemetry:
  enabled: true
  recorder: jsonl
  path: ./logs/telemetry.jsonl
  content_mode: metadata
  max_content_chars: 4000
  load_plugins: false
```

Relative JSONL `path` values are resolved from the YAML file's directory.
See `docs/telemetry.md` for privacy modes, custom recorder registration, and an
AgentCore adapter example.

## Troubleshooting

`agent_card.supportedInterfaces must contain at least one interface.`

The YAML file is using the old top-level `url` field or omitted the A2A
interface list. Add `supportedInterfaces`.

`instructions requires exactly one of 'text' or 'path'.`

Provide either inline text or a file path, not both.

`Invalid agent url`

The first supported interface URL must include a host and port, for example
`http://localhost:30000`.

`YAML MCP entries configure agent client connections only.`

The YAML loader does not start MCP servers. Start the MCP server separately, then
point the YAML `mcp.servers` entry at its host and port.
