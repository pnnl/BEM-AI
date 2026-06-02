from types import SimpleNamespace
import sys

import pytest

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents import agent_factory
from automa_ai.checkpoint.defaults import (
    DEFAULT_REDIS_CHECKPOINT_TTL_SECONDS,
    DEFAULT_REDIS_HEALTH_CHECK_INTERVAL,
    DEFAULT_REDIS_MAX_CHECKPOINTS_PER_THREAD,
    DEFAULT_REDIS_REFRESH_TTL_ON_READ,
    DEFAULT_REDIS_RETRY_ON_TIMEOUT,
    DEFAULT_REDIS_SOCKET_CONNECT_TIMEOUT,
    DEFAULT_REDIS_SOCKET_TIMEOUT,
)
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
    with pytest.raises(ValueError, match="No extra fields are allowed"):
        CheckpointerConfig.from_value(
            {"type": "default", "redis_url": "redis://localhost:6379"}
        )


def test_build_checkpointer_uses_plain_redis_saver(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakePlainRedisSaver:
        def __init__(
            self,
            redis_url: str,
            *,
            checkpoint_ttl_seconds: int | None,
            max_checkpoints_per_thread: int | None,
            refresh_ttl_on_read: bool,
            socket_timeout: float | None,
            socket_connect_timeout: float | None,
            health_check_interval: int | None,
            retry_on_timeout: bool,
        ) -> None:
            captured["redis_url"] = redis_url
            captured["checkpoint_ttl_seconds"] = checkpoint_ttl_seconds
            captured["max_checkpoints_per_thread"] = max_checkpoints_per_thread
            captured["refresh_ttl_on_read"] = refresh_ttl_on_read
            captured["socket_timeout"] = socket_timeout
            captured["socket_connect_timeout"] = socket_connect_timeout
            captured["health_check_interval"] = health_check_interval
            captured["retry_on_timeout"] = retry_on_timeout
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
    assert captured["checkpoint_ttl_seconds"] == DEFAULT_REDIS_CHECKPOINT_TTL_SECONDS
    assert captured["max_checkpoints_per_thread"] == (
        DEFAULT_REDIS_MAX_CHECKPOINTS_PER_THREAD
    )
    assert captured["refresh_ttl_on_read"] is DEFAULT_REDIS_REFRESH_TTL_ON_READ
    assert captured["socket_timeout"] == DEFAULT_REDIS_SOCKET_TIMEOUT
    assert captured["socket_connect_timeout"] == DEFAULT_REDIS_SOCKET_CONNECT_TIMEOUT
    assert captured["health_check_interval"] == DEFAULT_REDIS_HEALTH_CHECK_INTERVAL
    assert captured["retry_on_timeout"] is DEFAULT_REDIS_RETRY_ON_TIMEOUT
    assert checkpointer.setup_called is True
    assert cleanup == checkpointer.close


def test_build_checkpointer_passes_plain_redis_lifecycle_options(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakePlainRedisSaver:
        def __init__(
            self,
            redis_url: str,
            *,
            checkpoint_ttl_seconds: int | None,
            max_checkpoints_per_thread: int | None,
            refresh_ttl_on_read: bool,
            socket_timeout: float | None,
            socket_connect_timeout: float | None,
            health_check_interval: int | None,
            retry_on_timeout: bool,
        ) -> None:
            captured.update(
                {
                    "redis_url": redis_url,
                    "checkpoint_ttl_seconds": checkpoint_ttl_seconds,
                    "max_checkpoints_per_thread": max_checkpoints_per_thread,
                    "refresh_ttl_on_read": refresh_ttl_on_read,
                    "socket_timeout": socket_timeout,
                    "socket_connect_timeout": socket_connect_timeout,
                    "health_check_interval": health_check_interval,
                    "retry_on_timeout": retry_on_timeout,
                }
            )

        def setup(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(agent_factory, "PlainRedisSaver", FakePlainRedisSaver)

    agent_factory._build_checkpointer(
        {
            "type": "redis_plain",
            "redis_url": "localhost:6379",
            "checkpoint_ttl_seconds": 7200,
            "max_checkpoints_per_thread": 2,
            "refresh_ttl_on_read": False,
            "socket_timeout": 3.0,
            "socket_connect_timeout": 2.0,
            "health_check_interval": 15,
            "retry_on_timeout": False,
        }
    )

    assert captured == {
        "redis_url": "redis://localhost:6379",
        "checkpoint_ttl_seconds": 7200,
        "max_checkpoints_per_thread": 2,
        "refresh_ttl_on_read": False,
        "socket_timeout": 3.0,
        "socket_connect_timeout": 2.0,
        "health_check_interval": 15,
        "retry_on_timeout": False,
    }


def test_checkpointer_config_rejects_plain_redis_lifecycle_for_redis_stack() -> None:
    with pytest.raises(ValueError, match="only supported by redis_plain"):
        CheckpointerConfig.from_value(
            {
                "type": "redis_stack",
                "redis_url": "localhost:6379",
                "socket_timeout": 3.0,
            }
        )


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


def test_build_checkpointer_uses_agentcore_saver(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeAgentCoreMemorySaver:
        def __init__(self, memory_id: str, *, region_name: str) -> None:
            captured["memory_id"] = memory_id
            captured["region_name"] = region_name

    fake_agentcore_module = SimpleNamespace(
        AgentCoreMemorySaver=FakeAgentCoreMemorySaver
    )
    fake_boto3_module = SimpleNamespace(
        Session=lambda: SimpleNamespace(region_name="us-west-2")
    )

    monkeypatch.setitem(sys.modules, "langgraph_checkpoint_aws", fake_agentcore_module)
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3_module)

    checkpointer, cleanup = agent_factory._build_checkpointer(
        {"type": "agentcore", "memory_id": "mem-123"}
    )

    assert isinstance(checkpointer, FakeAgentCoreMemorySaver)
    assert captured == {"memory_id": "mem-123", "region_name": "us-west-2"}
    assert cleanup is None


def test_build_checkpointer_requires_agentcore_region(monkeypatch) -> None:
    fake_agentcore_module = SimpleNamespace(
        AgentCoreMemorySaver=lambda *args, **kwargs: object()
    )
    fake_boto3_module = SimpleNamespace(
        Session=lambda: SimpleNamespace(region_name=None)
    )

    monkeypatch.setitem(sys.modules, "langgraph_checkpoint_aws", fake_agentcore_module)
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3_module)

    with pytest.raises(ValueError, match="AWS region must be provided"):
        agent_factory._build_checkpointer({"type": "agentcore", "memory_id": "mem-123"})


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
        card={
            "name": "agent",
            "description": "desc",
            "version": "1.0.0",
            "defaultInputModes": ["text"],
            "defaultOutputModes": ["text"],
            "capabilities": {"streaming": True},
            "supportedInterfaces": [
                {
                    "url": "localhost:10000",
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "1.0",
                }
            ],
            "skills": [],
        },
        instructions="test",
        model_name="model",
        agent_type=GenericAgentType.LANGGRAPHCHAT,
        chat_model=GenericLLM.LITELLAMA,
        checkpointer_config="default",
    )

    factory()

    assert captured["checkpointer"] is sentinel
    assert captured["checkpointer_cleanup"] is sentinel_cleanup
