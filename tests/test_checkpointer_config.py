from types import SimpleNamespace

import pytest

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents import agent_factory
from automa_ai.config import CheckpointerConfig


@pytest.mark.parametrize("checkpointer_type", ["redis_plain", "redis_stack"])
def test_checkpointer_config_normalizes_redis_url(checkpointer_type: str) -> None:
    cfg = CheckpointerConfig.from_value(
        {"type": checkpointer_type, "redis_url": "localhost:6379"}
    )

    assert cfg.redis_url == "redis://localhost:6379"


@pytest.mark.parametrize("checkpointer_type", ["redis_plain", "redis_stack"])
def test_checkpointer_config_requires_redis_url(checkpointer_type: str) -> None:
    with pytest.raises(ValueError, match="redis_url is required"):
        CheckpointerConfig.from_value(checkpointer_type)


def test_checkpointer_config_rejects_redis_url_for_default() -> None:
    with pytest.raises(ValueError, match="only supported"):
        CheckpointerConfig.from_value(
            {"type": "default", "redis_url": "redis://localhost:6379"}
        )


def test_build_checkpointer_uses_plain_redis_saver(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakePlainRedisSaver:
        def __init__(self, redis_url: str) -> None:
            captured["redis_url"] = redis_url
            self.setup_called = False

        def setup(self) -> None:
            self.setup_called = True

        def close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(agent_factory, "PlainRedisSaver", FakePlainRedisSaver)

    checkpointer, cleanup = agent_factory._build_checkpointer(
        {"type": "redis_plain", "redis_url": "localhost:6379"}
    )

    assert isinstance(checkpointer, FakePlainRedisSaver)
    assert captured["redis_url"] == "redis://localhost:6379"
    assert checkpointer.setup_called is True
    assert cleanup == checkpointer.close


def test_build_checkpointer_uses_redis_stack_saver_and_calls_setup(monkeypatch) -> None:
    class FakeRedisSaver:
        def __init__(self, redis_url: str) -> None:
            self.redis_url = redis_url
            self.setup_called = False

        def setup(self) -> None:
            self.setup_called = True

    fake_module = SimpleNamespace(RedisSaver=FakeRedisSaver)
    import sys

    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.redis", fake_module)
    monkeypatch.setattr(agent_factory, "_validate_redis_stack_server", lambda url: None)

    checkpointer, cleanup = agent_factory._build_checkpointer(
        {"type": "redis_stack", "redis_url": "localhost:6379"}
    )

    assert isinstance(checkpointer, FakeRedisSaver)
    assert checkpointer.redis_url == "redis://localhost:6379"
    assert checkpointer.setup_called is True
    assert cleanup is None


def test_build_checkpointer_supports_context_manager_result(monkeypatch) -> None:
    class FakeRedisSaver:
        def __init__(self, redis_url: str) -> None:
            self.redis_url = redis_url
            self.setup_called = False

        def setup(self) -> None:
            self.setup_called = True

    class FakeContextManager:
        def __init__(self) -> None:
            self.saver = FakeRedisSaver("redis://localhost:6379")
            self.exited = False

        def __enter__(self) -> FakeRedisSaver:
            return self.saver

        def __exit__(self, exc_type, exc, tb) -> None:
            self.exited = True

    fake_ctx = FakeContextManager()
    fake_module = SimpleNamespace(
        RedisSaver=SimpleNamespace(from_conn_string=lambda redis_url: fake_ctx)
    )
    import sys

    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.redis", fake_module)
    monkeypatch.setattr(agent_factory, "_validate_redis_stack_server", lambda url: None)

    checkpointer, cleanup = agent_factory._build_checkpointer(
        {"type": "redis_stack", "redis_url": "localhost:6379"}
    )

    assert checkpointer is fake_ctx.saver
    assert checkpointer.setup_called is True
    assert cleanup is not None

    cleanup()

    assert fake_ctx.exited is True


def test_build_checkpointer_rejects_unsupported_redis_stack(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_factory,
        "_validate_redis_stack_server",
        lambda url: (_ for _ in ()).throw(ValueError("unsupported redis stack")),
    )

    with pytest.raises(ValueError, match="unsupported redis stack"):
        agent_factory._build_checkpointer(
            {"type": "redis_stack", "redis_url": "localhost:6379"}
        )


def test_agent_factory_passes_checkpointer_to_langgraph_chat(monkeypatch) -> None:
    sentinel = object()
    sentinel_cleanup = lambda: None
    captured: dict[str, object] = {}

    monkeypatch.setattr(agent_factory, "load_tool_plugins", lambda: None)
    monkeypatch.setattr(agent_factory, "resolve_chat_model", lambda *args: object())
    monkeypatch.setattr(
        agent_factory,
        "_build_checkpointer",
        lambda config: (sentinel, sentinel_cleanup),
    )

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
    assert captured["checkpointer_cleanup"] is sentinel_cleanup
