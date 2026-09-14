from examples.sim_chat_demo import chatbot as demo
from automa_ai.config.agent_spec import YamlAgentSpec


def test_sim_chat_demo_is_a_standalone_yaml_agent() -> None:
    spec = YamlAgentSpec.from_yaml_file(demo.SPEC_PATH)

    assert spec.agent is not None
    assert spec.agent_card is None
    assert spec.a2a is None
    assert spec.mcp is None
    assert spec.to_factory_kwargs()["tools_config"] == {
        "tools": [{"type": "web_search", "config": {"provider": "opensource"}}]
    }
