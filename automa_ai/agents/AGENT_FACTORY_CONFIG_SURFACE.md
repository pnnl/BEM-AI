# AgentFactory configuration surface (code-grounded)

This note documents the current top-level configuration surface observed from
`automa_ai/agents/agent_factory.py` and direct dependencies.

## Already represented in code today

`AgentFactory` constructor currently accepts and wires these categories:

- Agent identity and prompt:
  - `card` (name/description).
  - `instructions`.
- Model:
  - `chat_model` (`GenericLLM` provider enum).
  - `model_name`.
  - `model_base_url`, `api_key`, `api_version`.
- Runtime behavior:
  - `agent_type` (`GenericAgentType`).
  - `enable_metrics`, `debug`.
- MCP:
  - `mcp_configs` as `dict[str, MCPServerConfig]`, converted via
    `map_mcp_config_to_server_config`.
- Retrieval:
  - `retriever_spec` (`RetrieverProviderSpec | dict`) resolved by
    `resolve_retriever(...)`.
- Memory:
  - `memory_config` (`dict`) passed to `DefaultMemoryManager.from_config(...)`.
- Skills:
  - `skills_config` (`SkillsConfig | dict`) used to create `SkillManager`.
- Tools:
  - `tools_config` (`ToolsConfig | dict | list[dict]`) normalized to `ToolSpec`.
- Blackboard:
  - `blackboard_config` (`BlackboardConfig | dict`) used to build store,
    schema contract, and tools.
- Subagents:
  - `subagent_config` (`list[SubAgentSpec]`) attached as callable tools.

## Minimal wrapper needed for YAML loading

The main missing piece for YAML-first configuration is a thin, versioned top-level
spec that can parse these sections and convert them into existing `AgentFactory`
kwargs without changing existing Python paths. The wrapper can stay additive:

- parse YAML into a `YamlAgentSpec` pydantic model,
- map each section directly onto existing fields,
- create `AgentFactory` using `to_factory_kwargs()`.

This repository now includes that wrapper in `automa_ai/config/agent_spec.py`.
