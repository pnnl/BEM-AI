import pytest

from automa_ai.common import agent_registry
from automa_ai.common.agent_registry import A2AAgentServer


def _make_card(url: str) -> dict:
    return {
        "name": "Test Agent",
        "description": "Test agent card.",
        "version": "1.0.0",
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "capabilities": {
            "streaming": True,
            "pushNotifications": True,
        },
        "supportedInterfaces": [
            {
                "url": url,
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "skills": [
            {
                "id": "executor",
                "name": "Task Executor",
                "description": "Executes tasks.",
                "tags": ["execute"],
                "examples": ["Run a task."],
            }
        ],
    }


def test_base_url_path_parsed_from_no_scheme_url():
    card = _make_card("localhost:20000/a2a")
    server = A2AAgentServer(lambda: None, card)
    assert server.host_name == "localhost"
    assert server.port == 20000
    assert server.base_url_path == "/a2a"


def test_base_url_path_override_wins():
    card = _make_card("localhost:20000/a2a")
    server = A2AAgentServer(lambda: None, card, base_url_path="/permit")
    assert server.base_url_path == "/permit"


def test_server_run_closes_sync_agent(monkeypatch):
    calls: list[str] = []

    class DummyAgent:
        agent_name = "dummy"

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(agent_registry, "GenericAgentExecutor", lambda agent: object())
    monkeypatch.setattr(
        agent_registry, "DefaultRequestHandler", lambda **kwargs: object()
    )

    monkeypatch.setattr(
        agent_registry,
        "create_agent_card_routes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        agent_registry,
        "create_jsonrpc_routes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(agent_registry.uvicorn, "run", lambda *args, **kwargs: None)

    server = A2AAgentServer(lambda: DummyAgent(), _make_card("localhost:20000/a2a"))
    server.run()

    assert calls == ["closed"]


def test_close_agent_supports_async_close():
    calls: list[str] = []

    class DummyAgent:
        agent_name = "dummy"

        async def close(self):
            calls.append("closed")

    agent_registry._close_agent(DummyAgent())

    assert calls == ["closed"]

def test_health_check_default_response():
    card = _make_card("localhost:20000")
    server = A2AAgentServer(lambda: None, card)
    # Agent not built yet
    assert server._build_health_response() == {
        "status": "unhealthy",
        "agent": "Test Agent",
    }

    class DummyAgent:
        agent_name = "dummy"

    server._agent = DummyAgent()
    assert server._build_health_response() == {
        "status": "healthy",
        "agent": "Test Agent",
    }
    
