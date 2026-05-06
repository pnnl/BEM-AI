from __future__ import annotations

import pytest

from automa_ai.agents.remote_agent import (
    reset_subagent_emitter,
    set_subagent_emitter,
)
from automa_ai.config import agent_spec
from automa_ai.config.tools import ToolSpec
from automa_ai.tools import build_langchain_tools
from automa_ai.tools.yaml_agent.tool import YamlAgentTool, YamlAgentToolConfig


class FakeYamlAgent:
    agent_name = "FakeYamlAgent"

    def __init__(self) -> None:
        self.closed = False
        self.calls = []

    async def stream(
        self,
        query,
        context_id,
        task_id,
        user_id=None,
        metadata=None,
    ):
        self.calls.append(
            {
                "query": query,
                "context_id": context_id,
                "task_id": task_id,
                "user_id": user_id,
                "metadata": metadata,
            }
        )
        yield {
            "response_type": "text",
            "is_task_complete": False,
            "require_user_input": False,
            "content": "working",
        }
        yield {
            "response_type": "text",
            "is_task_complete": True,
            "require_user_input": False,
            "content": "done",
        }

    def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_yaml_agent_tool_streams_chunks_to_parent_emitter(monkeypatch, tmp_path):
    agent = FakeYamlAgent()

    def fake_loader(path):
        assert path == tmp_path / "agent.yaml"
        return lambda: agent

    monkeypatch.setattr(agent_spec, "load_agent_factory_from_yaml", fake_loader)
    events = []

    async def emit(event):
        events.append(event)

    token = set_subagent_emitter(emit)
    try:
        tool = YamlAgentTool(YamlAgentToolConfig(base_dir=str(tmp_path)))
        result = await tool.invoke(
            {
                "yaml_path": "agent.yaml",
                "query": "plan the work",
                "context_id": "session-1",
                "task_id": "task-1",
                "user_id": "user-1",
                "metadata": {"source": "test"},
            }
        )
    finally:
        reset_subagent_emitter(token)

    assert result == {
        "final": "done",
        "chunks": ["working", "done"],
        "context_id": "session-1",
        "task_id": "task-1",
        "requires_user_input": False,
    }
    assert agent.calls == [
        {
            "query": "plan the work",
            "context_id": "session-1",
            "task_id": "task-1",
            "user_id": "user-1",
            "metadata": {"source": "test"},
        }
    ]
    assert agent.closed is True
    assert [event.content for event in events] == ["working", "done"]
    assert events[-1].metadata["final"] is True


def test_yaml_agent_tool_is_registered() -> None:
    tools = build_langchain_tools([ToolSpec(type="yaml_agent", config={})])
    assert [tool.name for tool in tools] == ["yaml_agent"]
