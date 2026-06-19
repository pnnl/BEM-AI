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


def _write_headless_spec(path) -> None:
    path.write_text(
        """
spec_version: v1
agent_card:
  name: FakeYamlAgent
  description: Test headless YAML agent.
  version: 0.1.0
  capabilities:
    streaming: true
  supportedInterfaces:
    - url: http://localhost:0/
      protocolBinding: JSONRPC
      protocolVersion: "1.0"
  defaultInputModes: [text]
  defaultOutputModes: [text]
  skills: []
instructions:
  text: Test instruction.
model:
  provider: ollama
  name: llama3.1:8b
runtime:
  agent_type: langgraph-chat
""",
        encoding="utf-8",
    )


async def _fake_stream_result():
    yield {
        "response_type": "text",
        "is_task_complete": True,
        "require_user_input": False,
        "content": "awaited stream",
    }


class AwaitableStreamAgent(FakeYamlAgent):
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
        return _fake_stream_result()


@pytest.mark.asyncio
async def test_yaml_agent_tool_streams_chunks_to_parent_emitter(monkeypatch, tmp_path):
    agent = FakeYamlAgent()
    spec_path = tmp_path / "agent.yaml"
    _write_headless_spec(spec_path)

    def fake_loader(spec):
        assert spec.agent_card["name"] == "FakeYamlAgent"
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


@pytest.mark.asyncio
async def test_yaml_agent_tool_rejects_paths_outside_base_dir(tmp_path):
    base_dir = tmp_path / "subagents"
    base_dir.mkdir()
    outside = tmp_path / "outside.yaml"
    _write_headless_spec(outside)

    tool = YamlAgentTool(YamlAgentToolConfig(base_dir=str(base_dir)))

    with pytest.raises(ValueError, match="inside yaml_agent.config.base_dir"):
        await tool.invoke({"yaml_path": "../outside.yaml", "query": "run"})

    with pytest.raises(ValueError, match="inside yaml_agent.config.base_dir"):
        await tool.invoke({"yaml_path": str(outside), "query": "run"})


@pytest.mark.asyncio
async def test_yaml_agent_tool_rejects_non_file_yaml_path(tmp_path):
    spec_path = tmp_path / "agent.yaml"
    _write_headless_spec(spec_path)
    text_path = tmp_path / "agent.txt"
    text_path.write_text("not yaml", encoding="utf-8")

    tool = YamlAgentTool(YamlAgentToolConfig(base_dir=str(tmp_path)))

    with pytest.raises(ValueError, match=r"\.yaml or \.yml"):
        await tool.invoke({"yaml_path": "agent.txt", "query": "run"})

    with pytest.raises(ValueError, match=r"\.yaml or \.yml"):
        await tool.invoke({"yaml_path": ".", "query": "run"})

    with pytest.raises(ValueError, match="existing YAML file"):
        await tool.invoke({"yaml_path": "missing.yaml", "query": "run"})


@pytest.mark.asyncio
async def test_yaml_agent_tool_rejects_nested_yaml_agent_tool(tmp_path):
    spec_path = tmp_path / "agent.yaml"
    _write_headless_spec(spec_path)
    with spec_path.open("a", encoding="utf-8") as handle:
        handle.write(
            """
tools:
  tools:
    - type: yaml_agent
      config:
        base_dir: .
"""
        )

    tool = YamlAgentTool(YamlAgentToolConfig(base_dir=str(tmp_path)))

    with pytest.raises(ValueError, match="cannot enable yaml_agent"):
        await tool.invoke({"yaml_path": "agent.yaml", "query": "run"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fragment", "match"),
    [
        (
            """
mcp:
  servers:
    local:
      name: local
      host: localhost
      port: 10000
""",
            "cannot define mcp",
        ),
        (
            """
memory:
  stores: []
""",
            "cannot define memory",
        ),
        (
            """
checkpointer:
  type: redis_plain
  redis_url: redis://localhost:6379/0
""",
            "cannot define checkpointer",
        ),
        (
            """
subagents:
  - agent_card:
      name: NestedAgent
      description: Nested agent.
      version: 0.1.0
      capabilities:
        streaming: true
      supportedInterfaces:
        - url: http://localhost:1/
          protocolBinding: JSONRPC
          protocolVersion: "1.0"
      defaultInputModes: [text]
      defaultOutputModes: [text]
      skills: []
""",
            "cannot define nested subagents",
        ),
        (
            """
tools:
  config:
    enabled: true
""",
            "tools mapping must contain a tools list",
        ),
        (
            """
tools:
  tools:
    type: run_python
    config: {}
""",
            "tools must be a list or tools mapping",
        ),
        (
            """
tools:
  tools:
    - type: run_command
      config: {}
""",
            "custom dotted-path tools",
        ),
    ],
)
async def test_yaml_agent_tool_rejects_non_headless_spec_surface(
    tmp_path,
    fragment,
    match,
):
    spec_path = tmp_path / "agent.yaml"
    _write_headless_spec(spec_path)
    with spec_path.open("a", encoding="utf-8") as handle:
        handle.write(fragment)

    tool = YamlAgentTool(YamlAgentToolConfig(base_dir=str(tmp_path)))

    with pytest.raises(ValueError, match=match):
        await tool.invoke({"yaml_path": "agent.yaml", "query": "run"})


@pytest.mark.asyncio
async def test_yaml_agent_tool_accepts_custom_dotted_tool_spec(monkeypatch, tmp_path):
    agent = FakeYamlAgent()
    spec_path = tmp_path / "agent.yaml"
    _write_headless_spec(spec_path)
    with spec_path.open("a", encoding="utf-8") as handle:
        handle.write(
            """
tools:
  tools:
    - type: my_package.custom_tool
      config:
        option: true
"""
        )

    loaded_specs = []

    def fake_loader(spec):
        loaded_specs.append(spec)
        return lambda: agent

    monkeypatch.setattr(agent_spec, "load_agent_factory_from_yaml", fake_loader)
    tool = YamlAgentTool(YamlAgentToolConfig(base_dir=str(tmp_path)))

    result = await tool.invoke({"yaml_path": "agent.yaml", "query": "run"})

    assert result["final"] == "done"
    assert loaded_specs[0].tools["tools"][0]["type"] == "my_package.custom_tool"
    assert agent.closed is True


@pytest.mark.asyncio
async def test_yaml_agent_tool_accepts_awaitable_stream_result(monkeypatch, tmp_path):
    agent = AwaitableStreamAgent()
    spec_path = tmp_path / "agent.yaml"
    _write_headless_spec(spec_path)

    monkeypatch.setattr(
        agent_spec,
        "load_agent_factory_from_yaml",
        lambda spec: lambda: agent,
    )
    tool = YamlAgentTool(YamlAgentToolConfig(base_dir=str(tmp_path)))

    result = await tool.invoke({"yaml_path": "agent.yaml", "query": "run"})

    assert result["final"] == "awaited stream"
    assert result["chunks"] == ["awaited stream"]
    assert agent.closed is True


def test_yaml_agent_tool_is_registered() -> None:
    tools = build_langchain_tools([ToolSpec(type="yaml_agent", config={})])
    assert [tool.name for tool in tools] == ["yaml_agent"]
