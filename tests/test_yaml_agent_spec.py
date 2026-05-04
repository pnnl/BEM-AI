from __future__ import annotations

from pathlib import Path

import pytest

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.common.agent_registry import A2AAgentServer
from automa_ai.config.agent_spec import (
    YamlAgentSpec,
    load_a2a_server_from_yaml,
    load_agent_factory_from_yaml,
)


def _base_yaml(instructions: str = "text: be helpful") -> str:
    return f"""
spec_version: v1
agent_card:
  name: yaml-demo
  description: Agent loaded from YAML.
  version: 0.1.0
  defaultInputModes: [text]
  defaultOutputModes: [text]
  capabilities:
    streaming: true
  supportedInterfaces:
    - url: http://localhost:32123
      protocolBinding: JSONRPC
      protocolVersion: "1.0"
instructions:
  {instructions}
model:
  provider: ollama
  name: llama3.1:8b
runtime:
  agent_type: langgraph-chat
  enable_metrics: true
  debug: true
"""


def test_yaml_agent_spec_loads_inline_instructions() -> None:
    spec = YamlAgentSpec.from_yaml_text(_base_yaml())

    assert spec.resolve_instructions() == "be helpful"
    assert spec.model.provider == GenericLLM.OLLAMA
    assert spec.runtime.agent_type == GenericAgentType.LANGGRAPHCHAT


def test_yaml_agent_spec_loads_instruction_file_relative_to_yaml(
    tmp_path: Path,
) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    prompt_path = prompt_dir / "agent.md"
    prompt_path.write_text("Use the file prompt.", encoding="utf-8")

    spec_path = tmp_path / "agent.yaml"
    spec_path.write_text(_base_yaml("path: ./prompts/agent.md"), encoding="utf-8")

    spec = YamlAgentSpec.from_yaml_file(spec_path)

    assert spec.resolve_instructions() == "Use the file prompt."


def test_yaml_agent_spec_to_factory_kwargs_maps_current_surface() -> None:
    spec = YamlAgentSpec.from_yaml_text(
        _base_yaml()
        + """
mcp:
  servers:
    openstudio:
      name: openstudio_mcp
      host: localhost
      port: 10210
      transport: sse
      timeout: 15
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
        - url: http://localhost:32124
          protocolBinding: JSONRPC
          protocolVersion: "1.0"
tools:
  tools: []
checkpointer:
  type: default
"""
    )

    kwargs = spec.to_factory_kwargs()

    assert kwargs["card"]["name"] == "yaml-demo"
    assert kwargs["instructions"] == "be helpful"
    assert kwargs["model_name"] == "llama3.1:8b"
    assert kwargs["chat_model"] == GenericLLM.OLLAMA
    assert kwargs["agent_type"] == GenericAgentType.LANGGRAPHCHAT
    assert kwargs["mcp_configs"]["openstudio"].port == 10210
    assert kwargs["mcp_configs"]["openstudio"].timeout == 15
    assert kwargs["subagent_config"][0].name == "Math Agent"
    assert kwargs["tools_config"] == {"tools": []}
    assert kwargs["checkpointer_config"] == {"type": "default"}


def test_yaml_agent_spec_loads_subagent_from_spec_path(tmp_path: Path) -> None:
    subagent_path = tmp_path / "math_agent.yaml"
    subagent_path.write_text(
        _base_yaml().replace(
            "name: yaml-demo",
            "name: Math Agent",
            1,
        ),
        encoding="utf-8",
    )
    coordinator_path = tmp_path / "coordinator.yaml"
    coordinator_path.write_text(
        _base_yaml()
        + """
subagents:
  - spec_path: ./math_agent.yaml
""",
        encoding="utf-8",
    )

    spec = YamlAgentSpec.from_yaml_file(coordinator_path)
    kwargs = spec.to_factory_kwargs()

    assert kwargs["subagent_config"][0].name == "Math Agent"
    assert kwargs["subagent_config"][0].agent_card["name"] == "Math Agent"


def test_yaml_agent_spec_loads_subagent_from_card_path(tmp_path: Path) -> None:
    card_path = tmp_path / "math_card.json"
    card_path.write_text(
        """
{
  "name": "Math Agent",
  "description": "Handles arithmetic.",
  "supportedInterfaces": [
    {
      "url": "http://localhost:32124",
      "protocolBinding": "JSONRPC",
      "protocolVersion": "1.0"
    }
  ]
}
""",
        encoding="utf-8",
    )

    spec = YamlAgentSpec.from_yaml_text(
        _base_yaml()
        + """
subagents:
  - card_path: ./math_card.json
""",
        base_dir=tmp_path,
    )

    kwargs = spec.to_factory_kwargs()

    assert kwargs["subagent_config"][0].name == "Math Agent"
    assert kwargs["subagent_config"][0].description == "Handles arithmetic."


def test_yaml_agent_spec_allows_subagent_name_override() -> None:
    spec = YamlAgentSpec.from_yaml_text(
        _base_yaml()
        + """
subagents:
  - name: calculator
    agent_card:
      name: Math Agent
      description: Handles arithmetic.
      supportedInterfaces:
        - url: http://localhost:32124
          protocolBinding: JSONRPC
          protocolVersion: "1.0"
"""
    )

    kwargs = spec.to_factory_kwargs()

    assert kwargs["subagent_config"][0].name == "calculator"
    assert kwargs["subagent_config"][0].description == "Handles arithmetic."


def test_load_agent_factory_from_yaml(tmp_path: Path) -> None:
    spec_path = tmp_path / "agent.yaml"
    spec_path.write_text(_base_yaml(), encoding="utf-8")

    factory = load_agent_factory_from_yaml(spec_path)

    assert factory.model_name == "llama3.1:8b"
    assert (
        factory._card_data["supportedInterfaces"][0]["url"] == "http://localhost:32123"
    )


def test_load_agent_factory_from_existing_spec(tmp_path: Path) -> None:
    spec_path = tmp_path / "agent.yaml"
    spec_path.write_text(_base_yaml(), encoding="utf-8")
    spec = YamlAgentSpec.from_yaml_file(spec_path)

    factory = load_agent_factory_from_yaml(spec)

    assert factory.model_name == "llama3.1:8b"
    assert factory.instructions == "be helpful"


def test_load_a2a_server_from_yaml_uses_supported_interface(tmp_path: Path) -> None:
    spec_path = tmp_path / "agent.yaml"
    spec_path.write_text(
        _base_yaml()
        + """
server:
  base_url_path: /agent
  health_check_path: /ready
""",
        encoding="utf-8",
    )

    server = load_a2a_server_from_yaml(spec_path)

    assert isinstance(server, A2AAgentServer)
    assert server.name == "yaml-demo"
    assert server.host_name == "localhost"
    assert server.port == 32123
    assert server.base_url_path == "/agent"
    assert server.health_check_path == "/ready"


def test_load_a2a_server_from_existing_spec(tmp_path: Path) -> None:
    spec_path = tmp_path / "agent.yaml"
    spec_path.write_text(_base_yaml(), encoding="utf-8")
    spec = YamlAgentSpec.from_yaml_file(spec_path)

    server = load_a2a_server_from_yaml(spec)

    assert server.name == "yaml-demo"
    assert server.port == 32123


def test_yaml_agent_spec_rejects_old_card_without_supported_interfaces() -> None:
    with pytest.raises(ValueError, match="supportedInterfaces"):
        YamlAgentSpec.from_yaml_text(
            """
spec_version: v1
agent_card:
  name: old-card
  description: Missing A2A 1.0 interfaces.
  url: http://localhost:9999
instructions:
  text: be helpful
model:
  provider: ollama
  name: llama3.1:8b
"""
        )


def test_yaml_agent_spec_requires_one_instruction_source() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        YamlAgentSpec.from_yaml_text(
            """
spec_version: v1
agent_card:
  name: bad-instructions
  description: Invalid instructions.
  supportedInterfaces:
    - url: http://localhost:32123
      protocolBinding: JSONRPC
      protocolVersion: "1.0"
instructions:
  text: be helpful
  path: ./prompt.md
model:
  provider: ollama
  name: llama3.1:8b
"""
        )


def test_yaml_agent_spec_requires_one_subagent_source() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        YamlAgentSpec.from_yaml_text(
            _base_yaml()
            + """
subagents:
  - spec_path: ./math_agent.yaml
    card_path: ./math_card.json
"""
        )
