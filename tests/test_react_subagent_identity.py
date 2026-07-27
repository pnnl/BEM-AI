from __future__ import annotations

import pytest

from automa_ai.agents.react_langgraph_agent import GenericLangGraphReactAgent
from automa_ai.agents.remote_agent import get_subagent_user_id


def _agent() -> GenericLangGraphReactAgent:
    return GenericLangGraphReactAgent(
        agent_name="react_identity_test",
        description="Test agent.",
        instructions="Test instructions.",
        chat_model=None,
        response_format=None,
    )


@pytest.mark.asyncio
async def test_react_agent_invoke_scopes_user_id_for_subagent_tools() -> None:
    captured: dict[str, str | None] = {}

    class Graph:
        async def ainvoke(self, inputs, config):
            captured["user_id"] = get_subagent_user_id()
            return {"messages": []}

    agent = _agent()
    agent.graph = Graph()

    await agent.invoke("Analyze the project.", "session-123", user_id="user-456")

    assert captured == {"user_id": "user-456"}
    assert get_subagent_user_id() is None


@pytest.mark.asyncio
async def test_react_agent_stream_scopes_user_id_for_subagent_tools() -> None:
    captured: dict[str, str | None] = {}

    class Graph:
        async def astream(self, inputs, config, stream_mode):
            captured["user_id"] = get_subagent_user_id()
            if False:
                yield {}

    agent = _agent()
    agent.graph = Graph()

    async for _ in agent.stream(
        "Analyze the project.",
        "session-123",
        "task-123",
        user_id="user-456",
    ):
        pass

    assert captured == {"user_id": "user-456"}
    assert get_subagent_user_id() is None
