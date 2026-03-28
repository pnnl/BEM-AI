import pytest

from a2a.types import AgentCard, AgentCapabilities, AgentSkill

from automa_ai.common import agent_registry
from automa_ai.common.agent_registry import A2AAgentServer


def _make_card(url: str) -> AgentCard:
    skill = AgentSkill(
        id="executor",
        name="Task Executor",
        description="Executes tasks.",
        tags=["execute"],
        examples=["Run a task."],
    )
    return AgentCard(
        name="Test Agent",
        description="Test agent card.",
        url=url,
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(
            streaming=True, push_notifications=True, state_transition_history=False
        ),
        skills=[skill],
        supports_authenticated_extended_card=False,
    )


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

    class DummyApp:
        def build(self):
            return object()

    monkeypatch.setattr(
        agent_registry,
        "A2AStarletteApplication",
        lambda **kwargs: DummyApp(),
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
