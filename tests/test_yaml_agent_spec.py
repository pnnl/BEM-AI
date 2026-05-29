from __future__ import annotations

from pathlib import Path

import pytest
from google.protobuf.json_format import MessageToDict

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
budget:
  max_input_tokens: 1000
  store:
    backend: sqlite
    db_path: ./token_usage.db
telemetry:
  enabled: true
  recorder: jsonl
  path: ./logs/telemetry.jsonl
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
    assert kwargs["budget_config"]["max_input_tokens"] == 1000
    assert kwargs["budget_config"]["store"]["backend"] == "sqlite"
    assert kwargs["telemetry_config"]["enabled"] is True
    assert kwargs["telemetry_config"]["recorder"] == "jsonl"


def test_yaml_agent_spec_rebases_telemetry_jsonl_path(tmp_path: Path) -> None:
    spec = YamlAgentSpec.from_yaml_text(
        _base_yaml()
        + """
telemetry:
  enabled: true
  recorder: jsonl
  path: ./logs/telemetry.jsonl
""",
        base_dir=tmp_path,
    )

    kwargs = spec.to_factory_kwargs()

    assert kwargs["telemetry_config"]["path"] == str(
        tmp_path / "logs" / "telemetry.jsonl"
    )


def test_yaml_agent_spec_rebases_budget_sqlite_db_path(tmp_path: Path) -> None:
    spec = YamlAgentSpec.from_yaml_text(
        _base_yaml()
        + """
budget:
  store:
    backend: sqlite
    db_path: ./ledger/token_usage.db
""",
        base_dir=tmp_path,
    )

    kwargs = spec.to_factory_kwargs()

    assert kwargs["budget_config"]["store"]["db_path"] == str(
        tmp_path / "ledger" / "token_usage.db"
    )


def test_yaml_agent_spec_accepts_custom_token_usage_store_config() -> None:
    spec = YamlAgentSpec.from_yaml_text(
        _base_yaml()
        + """
budget:
  store:
    backend: dynamodb
    table_name: automa-token-usage
    region_name: us-west-2
"""
    )

    kwargs = spec.to_factory_kwargs()

    assert kwargs["budget_config"]["store"] == {
        "backend": "dynamodb",
        "table_name": "automa-token-usage",
        "region_name": "us-west-2",
    }


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


def test_yaml_agent_spec_rejects_legacy_subagent_card_path(tmp_path: Path) -> None:
    card_path = tmp_path / "legacy_card.json"
    card_path.write_text(
        """
{
  "name": "Legacy Agent",
  "description": "Uses old top-level url.",
  "url": "http://localhost:32124"
}
""",
        encoding="utf-8",
    )

    spec = YamlAgentSpec.from_yaml_text(
        _base_yaml()
        + """
subagents:
  - card_path: ./legacy_card.json
""",
        base_dir=tmp_path,
    )

    with pytest.raises(ValueError, match="supportedInterfaces"):
        spec.to_factory_kwargs()


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


def test_yaml_agent_spec_rebases_skill_paths_from_spec_directory(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "configs"
    spec_dir.mkdir()
    spec_path = spec_dir / "agent.yaml"
    spec_path.write_text(
        _base_yaml()
        + """
skills:
  enabled: true
  allowed_roots:
    - ./skills
  registry:
    direct: ./skills/direct.md
    mapped:
      path: ./skills/mapped.md
      format: markdown
""",
        encoding="utf-8",
    )

    spec = YamlAgentSpec.from_yaml_file(spec_path)
    skills = spec.to_factory_kwargs()["skills_config"]

    assert skills["allowed_roots"] == [str(spec_dir / "skills")]
    assert skills["registry"]["direct"] == str(spec_dir / "skills" / "direct.md")
    assert skills["registry"]["mapped"]["path"] == str(
        spec_dir / "skills" / "mapped.md"
    )


def test_yaml_agent_spec_rebases_blackboard_base_dir_from_spec_directory(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "configs"
    spec_dir.mkdir()
    spec_path = spec_dir / "agent.yaml"
    spec_path.write_text(
        _base_yaml()
        + """
blackboard:
  enabled: true
  store:
    backend: local_json
    base_dir: ./.blackboards
  schema_name: task
  schema_version: v1
  schema:
    type: object
""",
        encoding="utf-8",
    )

    spec = YamlAgentSpec.from_yaml_file(spec_path)
    blackboard = spec.to_factory_kwargs()["blackboard_config"]

    assert blackboard["store"]["base_dir"] == str(spec_dir / ".blackboards")


def test_yaml_agent_spec_rebases_run_python_workspace_root_from_spec_directory(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "configs"
    spec_dir.mkdir()
    spec_path = spec_dir / "agent.yaml"
    spec_path.write_text(
        _base_yaml()
        + """
tools:
  tools:
    - type: run_python
      config:
        workspace_root: ./workspace
        failure_experience_path: ./logs/python_script_failure_experience.jsonl
""",
        encoding="utf-8",
    )

    spec = YamlAgentSpec.from_yaml_file(spec_path)
    tools = spec.to_factory_kwargs()["tools_config"]

    assert tools["tools"][0]["config"]["workspace_root"] == str(spec_dir / "workspace")
    assert tools["tools"][0]["config"]["failure_experience_path"] == str(
        spec_dir / "logs/python_script_failure_experience.jsonl"
    )


def test_yaml_agent_spec_rebases_yaml_agent_base_dir_from_spec_directory(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "configs"
    spec_dir.mkdir()
    spec_path = spec_dir / "agent.yaml"
    spec_path.write_text(
        _base_yaml()
        + """
tools:
  tools:
    - type: yaml_agent
      config:
        base_dir: ./subagents
""",
        encoding="utf-8",
    )

    spec = YamlAgentSpec.from_yaml_file(spec_path)
    tools = spec.to_factory_kwargs()["tools_config"]

    assert tools["tools"][0]["config"]["base_dir"] == str(spec_dir / "subagents")


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
    card_data = MessageToDict(server.card, preserving_proto_field_name=False)
    assert card_data["supportedInterfaces"][0]["url"] == "http://localhost:32123/agent"


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


def test_yaml_agent_spec_rejects_wrong_supported_interfaces_shape() -> None:
    with pytest.raises(ValueError, match=r"supportedInterfaces\[0\] must be a mapping"):
        YamlAgentSpec.from_yaml_text(
            """
spec_version: v1
agent_card:
  name: bad-card
  description: Bad interface shape.
  supportedInterfaces:
    - http://localhost:9999
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
