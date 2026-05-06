# BEM-AI Agent Guide

This guide only keeps the current, useful rules for updating and migrating BEM-AI projects.

## Current default pattern

Use this pattern for new work and for legacy migrations:

- Prefer defining new AUTOMA-AI agents with a YAML agent spec and booting them
  with `load_agent_factory_from_yaml(...)` or `load_a2a_server_from_yaml(...)`.
- Use direct `AgentFactory(...)` construction only when YAML is not a good fit
  for the task.
- Prefer `GenericAgentType.LANGGRAPHCHAT`.
- Coordinate multiple agents with `SubAgentSpec`.
- Start services with `A2AServerManager` and `MCPServerManager`.
- Pass **plain dict** agent cards at the example boundary.
- Use the A2A 1.0 card shape with `supportedInterfaces`.
- Use `blackboard_config` when subagents need shared state.

When adding or editing YAML specs, carefully review the full spec in
`docs/yaml_agent_spec.md` and validate the YAML file from its actual location.
Relative paths for instructions, subagent specs/cards, tools, skills, and
blackboards are resolved from the YAML file's directory, so moving a spec or
loading it from the wrong path can cause schema or path validation failures.

Avoid these legacy paths:

- `GenericAgentType.ORCHESTRATOR`
- `automa_ai.network.agentic_network`
- `automa_ai.network.chat_network`
- `orchestrator_local_agent.py`
- `orchestrator_network_agent.py`
- workflow-graph orchestration for new examples

## A2A 1.0 rules

The repo now targets the current protobuf-backed A2A SDK.

- Do not construct cards with `AgentCard(..., url=..., supports_authenticated_extended_card=...)`.
- Do not load JSON cards with `AgentCard(**data)`.
- Prefer plain dict cards in examples and fixtures.
- Use current JSON fields:
  - `supportedInterfaces`
  - `defaultInputModes`
  - `defaultOutputModes`
  - `capabilities.streaming`
  - `capabilities.pushNotifications` when needed
- If runtime code needs a typed card, convert inside the runtime layer, not in the example bootstrap.

## Multi-agent migration checklist

When migrating a legacy example:

1. Replace `MultiAgentNetwork` or service-orchestrator wrappers with:
   - `MCPServerManager`
   - `A2AServerManager`
   - explicit `A2AAgentServer(...)` registration
2. Replace the legacy orchestrator agent with:
   - one coordinator agent built by `AgentFactory`
   - subagents wired through `SubAgentSpec`
3. Replace old card constructors and old card JSON schema with the A2A 1.0 shape.
4. Keep the server bootstrap explicit in one script.
5. If agents need shared files, model paths, or outputs, add a simple local JSON blackboard.
6. Keep prompts narrow and task-specific. Avoid complex workflow engines when simple delegation is enough.

## Shared state guidance

Use a blackboard only when agents need to share state across turns or across subagents.

- Preferred backend for examples: local JSON.
- Keep the schema permissive unless strict validation is necessary.
- Use simple paths and simple operations.
- Let the coordinator treat the blackboard as the source of truth.

## AgentFactory guidance

Useful `AgentFactory` integration points:

- `mcp_configs` for MCP tool servers
- `subagent_config` for A2A delegation
- `retriever_spec` for retrieval-backed agents
- `skills_config` for prompt skills
- `tools_config` for default tools; use built-in short names such as `web_search` or fully qualified dotted paths for custom `@tool` functions
- `memory_config` for long/short-term memory
- `blackboard_config` for shared workflow state

## Retrieval, skills, and memory

Only keep these points in mind while migrating:

- Retrieval providers must be registered before `AgentFactory(...)` resolves `retriever_spec`.
- Skills are loaded through `skills_config`; do not hardcode skill text into runtime code when file-backed skills are enough.
- Memory stores should follow the registry/config pattern already used by `DefaultMemoryManager`.

## Example file conventions

For example apps:

- Keep one server bootstrap script.
- Keep one Streamlit UI script.
- Keep agent cards as plain JSON fixtures when they help readability.
- Keep MCP configs and prompts in the server bootstrap so startup behavior is obvious.
- Update the example README whenever architecture or run instructions change.

## Focused verification

After each migration step, use the smallest relevant check:

- `py_compile` for touched Python files
- a narrow import smoke check for updated modules
- the nearest targeted test file
- JSON parse checks for migrated card fixtures

If a test fails because of sandboxed sockets or missing optional system dependencies, state that clearly and stop expanding scope.

## Learning Mode
When a user explicitly expressed that they are currently onboarding or learning this repository, the agent shall follow the additional instructions in the learning mode.

### BEFORE AGENT WRITING CODE
- Explain what you're about to do and why
- Break it down into steps the user can follow
- Wait for the user's OK before proceeding

### AFTER WRITING CODE
- Explain what each part does
- Ask the user **3 questions** to verify their understanding
- If the user answer wrong, explain again until the user get it
- **Do NOT let the user commit** until the user pass your questions

### GENERAL RULES FOR LEARNING MODE
- **Never** generate code the user can't explain
- If the user asks for something complex, **suggest simpler alternatives**
- Treat every session as a **teaching opportunity**
- Be direct, **Tell the user when they are doing something wrong**
