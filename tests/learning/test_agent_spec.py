from __future__ import annotations

from pathlib import Path

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.config.agent_spec import YamlAgentSpec
from automa_ai.config.learning import LearningWorkflowConfig


def test_yaml_agent_spec_load_and_validate(tmp_path: Path) -> None:
    spec_path = tmp_path / "agent.yaml"
    spec_path.write_text(
        """
spec_version: v1
agent:
  name: demo
  description: demo agent
  instructions: be helpful
model:
  provider: ollama
  model_name: llama3.1:8b
  base_url: http://localhost:11434
runtime:
  agent_type: langgraph-chat
  enable_metrics: true
  debug: true
retriever:
  enabled: false
memory:
  short_term_limit: 5
skills:
  enabled: true
  registry: {}
tools:
  tools: []
blackboard:
  enabled: false
  backend: local_json
  schema_name: task
  schema_version: v1
  schema: {type: object}
learning:
  enabled: true
  output_dir: artifacts/tests
""",
        encoding="utf-8",
    )

    spec = YamlAgentSpec.from_yaml_file(spec_path)
    assert spec.spec_version == "v1"
    assert spec.model.provider == GenericLLM.OLLAMA
    assert spec.runtime.agent_type == GenericAgentType.LANGGRAPHCHAT


def test_yaml_agent_spec_to_factory_kwargs_maps_existing_surface() -> None:
    spec = YamlAgentSpec.from_yaml_text(
        """
spec_version: v1
agent:
  name: mapper
  description: map test
  instructions: map config
model:
  provider: openai
  model_name: gpt-4o-mini
runtime:
  agent_type: langgraph-chat
mcp:
  servers:
    local:
      name: local
      host: localhost
      port: 9999
      transport: sse
learning:
  enabled: true
"""
    )

    kwargs = spec.to_factory_kwargs()

    assert kwargs["card"].name == "mapper"
    assert kwargs["chat_model"] == GenericLLM.OPENAI
    assert kwargs["agent_type"] == GenericAgentType.LANGGRAPHCHAT
    assert "local" in kwargs["mcp_configs"]
    assert kwargs["mcp_configs"]["local"].port == 9999
    assert kwargs["mcp_configs"]["local"].agent_cards_dir == "/automa_ai"
    assert isinstance(kwargs["learning_config"], LearningWorkflowConfig)
