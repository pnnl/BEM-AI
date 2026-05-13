from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.agent_factory import AgentFactory


def _card():
    return {
        "name": "budget-agent",
        "description": "Agent for budget tests.",
        "supportedInterfaces": [
            {
                "url": "http://localhost:34567",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
    }


def test_agent_factory_disabled_budget_does_not_create_usage_store(monkeypatch):
    called = False

    def fail_if_called(config):
        nonlocal called
        called = True
        raise AssertionError("store should not be created for disabled budgets")

    monkeypatch.setattr(
        "automa_ai.agents.agent_factory.create_token_usage_store",
        fail_if_called,
    )
    monkeypatch.setattr(
        "automa_ai.agents.agent_factory.resolve_chat_model",
        lambda *args, **kwargs: None,
    )

    agent = AgentFactory(
        card=_card(),
        instructions="test",
        model_name="dummy",
        agent_type=GenericAgentType.LANGGRAPHCHAT,
        chat_model=GenericLLM.OLLAMA,
        budget_config={"enabled": False, "max_session_tokens": 1},
    ).get_agent()

    assert called is False
    assert agent.budget_config.enabled is False
    assert agent.token_usage_store is None
