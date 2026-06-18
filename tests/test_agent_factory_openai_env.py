from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents import agent_factory
from automa_ai.models import chat as model_chat
import pytest


def test_resolve_chat_model_uses_openai_api_key_env(monkeypatch):
    captured: dict[str, object] = {}

    class DummyChatOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.delenv("OPENAI_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(
        model_chat,
        "_load_openai_chat_models",
        lambda: (DummyChatOpenAI, object),
    )

    model_chat.resolve_chat_model(
        GenericLLM.OPENAI,
        "gpt-4o-mini",
        GenericAgentType.LANGGRAPHCHAT,
    )

    assert captured["model"] == "gpt-4o-mini"
    assert captured["api_key"].get_secret_value() == "test-openai-key"


def test_resolve_chat_model_claude_omits_temperature(monkeypatch):
    captured: dict[str, object] = {}

    class DummyChatAnthropic:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        model_chat, "_load_anthropic_chat_model", lambda: DummyChatAnthropic
    )

    model_chat.resolve_chat_model(
        GenericLLM.CLAUDE,
        "claude-opus-4-20250514",
        GenericAgentType.LANGGRAPHCHAT,
        api_key="test-anthropic-key",
    )

    assert captured["model_name"] == "claude-opus-4-20250514"
    assert captured["api_key"].get_secret_value() == "test-anthropic-key"
    assert "temperature" not in captured
    assert "stop" not in captured


def test_resolve_chat_model_uses_configured_gemini_max_retries(monkeypatch):
    captured: dict[str, object] = {}

    class DummyChatGoogleGenerativeAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setattr(
        model_chat,
        "_load_gemini_chat_model",
        lambda: DummyChatGoogleGenerativeAI,
    )

    model_chat.resolve_chat_model(
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
        model_chat,
        "_load_gemini_chat_model",
        lambda: DummyChatGoogleGenerativeAI,
    )

    model_chat.resolve_chat_model(
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
        model_chat,
        "_load_gemini_chat_model",
        lambda: DummyChatGoogleGenerativeAI,
    )

    with pytest.raises(
        ValueError, match="model_max_retries must be convertible to an integer"
    ):
        model_chat.resolve_chat_model(
            GenericLLM.GEMINI,
            "gemini-2.5-flash",
            GenericAgentType.LANGGRAPHCHAT,
            model_max_retries="not-a-number",
        )


def test_agent_factory_still_exports_resolve_chat_model():
    assert agent_factory.resolve_chat_model is model_chat.resolve_chat_model


def test_resolve_chat_model_openai_compatible_requires_base_url(monkeypatch):
    class DummyChatOpenAI:
        def __init__(self, **kwargs) -> None:
            pass

    monkeypatch.setattr(
        model_chat,
        "_load_openai_chat_models",
        lambda: (DummyChatOpenAI, object),
    )

    with pytest.raises(ValueError, match="non-empty base_url"):
        model_chat.resolve_chat_model(
            GenericLLM.OPENAI_COMPATIBLE,
            "local-model",
            GenericAgentType.LANGGRAPHCHAT,
            api_key="test-key",
        )


def test_resolve_chat_model_openai_compatible_uses_public_chat_openai(monkeypatch):
    captured: dict[str, object] = {}

    class DummyChatOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        model_chat,
        "_load_openai_chat_models",
        lambda: (DummyChatOpenAI, object),
    )

    model_chat.resolve_chat_model(
        GenericLLM.OPENAI_COMPATIBLE,
        "llama-compatible",
        GenericAgentType.LANGGRAPHCHAT,
        base_url="https://models.example/v1",
        api_key=" explicit-key ",
        model_kwargs={"top_p": 0.8},
        default_headers={"X-Provider": "local"},
        extra_body={"metadata": {"tenant": "test"}},
    )

    assert captured["model"] == "llama-compatible"
    assert captured["base_url"] == "https://models.example/v1"
    assert captured["api_key"].get_secret_value() == "explicit-key"
    assert captured["model_kwargs"] == {"top_p": 0.8}
    assert captured["default_headers"] == {"X-Provider": "local"}
    assert captured["extra_body"] == {"metadata": {"tenant": "test"}}


def test_resolve_chat_model_openai_compatible_extracts_bearer_token(monkeypatch):
    captured: dict[str, object] = {}

    class DummyChatOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        model_chat,
        "_load_openai_chat_models",
        lambda: (DummyChatOpenAI, object),
    )

    model_chat.resolve_chat_model(
        GenericLLM.OPENAI_COMPATIBLE,
        "llama-compatible",
        GenericAgentType.LANGGRAPHCHAT,
        base_url="https://models.example/v1",
        default_headers={"Authorization": "Bearer header-token"},
    )

    assert captured["api_key"].get_secret_value() == "header-token"
