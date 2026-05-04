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
  enable_metrics: false
  debug: false
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
  enable_metrics: true
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

checkpointer:
  type: default
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
- `enable_metrics`: Enables metrics collection when supported. Defaults to
  `false`.
- `debug`: Enables debug behavior in the underlying agent. Defaults to `false`.

### `server`

Optional object for the `A2AAgentServer` wrapper.

- `log_dir`: Log directory. Defaults to `./logs`.
- `base_url_path`: Optional mount path override. If omitted, the path from
  `agent_card.supportedInterfaces[0].url` is used.
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
means the built-in `run_python` tool's `config.workspace_root` is resolved from
the YAML file's directory. Other tool config strings are passed through as-is.
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
    config: {}
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

The exact fields depend on the registered memory manager and store provider.

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
```

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
