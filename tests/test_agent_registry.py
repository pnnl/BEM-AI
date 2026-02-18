import pytest

from a2a.types import AgentCard, AgentCapabilities, AgentSkill

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
