from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents import agent_factory
import pytest


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


def test_resolve_chat_model_uses_configured_gemini_max_retries(monkeypatch):
    captured: dict[str, object] = {}

    class DummyChatGoogleGenerativeAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setattr(
        agent_factory, "ChatGoogleGenerativeAI", DummyChatGoogleGenerativeAI
    )

    agent_factory.resolve_chat_model(
        GenericLLM.GEMINI,
        "gemini-2.5-flash",
        GenericAgentType.LANGGRAPHCHAT,
        model_max_retries=5,
    )

    assert captured["model"] == "gemini-2.5-flash"
    assert captured["max_retries"] == 5


def test_resolve_chat_model_gemini_negative_max_retries_clamped_to_zero(monkeypatch):
    captured: dict[str, object] = {}

    class DummyChatGoogleGenerativeAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setattr(
        agent_factory, "ChatGoogleGenerativeAI", DummyChatGoogleGenerativeAI
    )

    agent_factory.resolve_chat_model(
        GenericLLM.GEMINI,
        "gemini-2.5-flash",
        GenericAgentType.LANGGRAPHCHAT,
        model_max_retries=-3,
    )

    assert captured["max_retries"] == 0


def test_resolve_chat_model_gemini_invalid_max_retries_raises(monkeypatch):
    class DummyChatGoogleGenerativeAI:
        def __init__(self, **kwargs) -> None:
            pass

    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setattr(
        agent_factory, "ChatGoogleGenerativeAI", DummyChatGoogleGenerativeAI
    )

    with pytest.raises(ValueError, match="model_max_retries must be a non-negative integer"):
        agent_factory.resolve_chat_model(
            GenericLLM.GEMINI,
            "gemini-2.5-flash",
            GenericAgentType.LANGGRAPHCHAT,
            model_max_retries="not-a-number",
        )
