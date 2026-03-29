from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents import agent_factory


def test_resolve_chat_model_uses_openai_api_key_env(monkeypatch):
    captured: dict[str, object] = {}

    class DummyChatOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.delenv("OPENAI_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(agent_factory, "ChatOpenAI", DummyChatOpenAI)

    agent_factory.resolve_chat_model(
        GenericLLM.OPENAI,
        "gpt-4o-mini",
        GenericAgentType.LANGGRAPHCHAT,
    )

    assert captured["model"] == "gpt-4o-mini"
    assert captured["api_key"].get_secret_value() == "test-openai-key"
