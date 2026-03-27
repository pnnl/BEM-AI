from types import SimpleNamespace

import pytest

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents import agent_factory
from automa_ai.config import CheckpointerConfig


def test_checkpointer_config_normalizes_redis_url() -> None:
    cfg = CheckpointerConfig.from_value(
        {"type": "redis", "redis_url": "localhost:6379"}
    )

    assert cfg.redis_url == "redis://localhost:6379"


def test_checkpointer_config_requires_redis_url() -> None:
    with pytest.raises(ValueError, match="redis_url is required"):
        CheckpointerConfig.from_value("redis")


def test_checkpointer_config_rejects_redis_url_for_default() -> None:
    with pytest.raises(ValueError, match="only supported"):
        CheckpointerConfig.from_value(
            {"type": "default", "redis_url": "redis://localhost:6379"}
        )


def test_build_checkpointer_uses_redis_saver_and_calls_setup(monkeypatch) -> None:
    class FakeRedisSaver:
        def __init__(self, redis_url: str) -> None:
            self.redis_url = redis_url
            self.setup_called = False

        def setup(self) -> None:
            self.setup_called = True

    fake_module = SimpleNamespace(RedisSaver=FakeRedisSaver)
    import sys

    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.redis", fake_module)

    checkpointer = agent_factory._build_checkpointer(
        {"type": "redis", "redis_url": "localhost:6379"}
    )

    assert isinstance(checkpointer, FakeRedisSaver)
    assert checkpointer.redis_url == "redis://localhost:6379"
    assert checkpointer.setup_called is True


def test_agent_factory_passes_checkpointer_to_langgraph_chat(monkeypatch) -> None:
    sentinel = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(agent_factory, "load_tool_plugins", lambda: None)
    monkeypatch.setattr(agent_factory, "resolve_chat_model", lambda *args: object())
    monkeypatch.setattr(agent_factory, "_build_checkpointer", lambda config: sentinel)

    class DummyLangGraphChatAgent:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        agent_factory, "GenericLangGraphChatAgent", DummyLangGraphChatAgent
    )

    factory = agent_factory.AgentFactory(
        card=SimpleNamespace(name="agent", description="desc"),
        instructions="test",
        model_name="model",
        agent_type=GenericAgentType.LANGGRAPHCHAT,
        chat_model=GenericLLM.LITELLAMA,
        checkpointer_config="default",
    )

    factory()

    assert captured["checkpointer"] is sentinel
