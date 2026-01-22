import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessageChunk, ToolMessage

from automa_ai.agents.langgraph_chatagent import GenericLangGraphChatAgent
from automa_ai.agents.remote_agent import StreamEvent
from automa_ai.common.message_accumulator import AIMessageAccumulator, ARTIFACT_START, ARTIFACT_END


class DummyRetriever:
    async def asimilarity_search_by_vector(self, query: str) -> str:
        return "retrieved context"


class DummyMemoryEntry:
    def __init__(self, timestamp: str, content: str) -> None:
        self.timestamp = timestamp
        self.content = content


class DummyMemoryManager:
    async def retrieve_memories(self, *args, **kwargs):
        return [DummyMemoryEntry("2024-01-01", "remember this")]


def build_agent(*, retriever=None, memory_manager=None) -> GenericLangGraphChatAgent:
    return GenericLangGraphChatAgent(
        agent_name="test-agent",
        description="test",
        instructions="test",
        chat_model=None,
        response_format=None,
        retriever=retriever,
        memory_manager=memory_manager,
    )


def build_agent_with_skills() -> GenericLangGraphChatAgent:
    def _load_skill(name: str) -> str:
        return f"skill:{name}"

    skill_manager = SimpleNamespace(enabled=True, load=_load_skill)
    agent = GenericLangGraphChatAgent(
        agent_name="test-agent",
        description="test",
        instructions="test",
        chat_model=None,
        response_format=None,
        skills_manager=skill_manager,
    )
    agent.graph = SimpleNamespace(
        tools=[SimpleNamespace(name="load_skill"), SimpleNamespace(name="other_tool")]
    )
    return agent


@pytest.mark.asyncio
async def test_build_stream_inputs_includes_context_and_memory():
    agent = build_agent(retriever=DummyRetriever(), memory_manager=DummyMemoryManager())
    inputs = await agent._build_stream_inputs("hello", "session-1")

    system_content = inputs["messages"][0]["content"]
    assert "retrieved context" in system_content
    assert "past conversations" in system_content
    assert "2024-01-01: remember this" in system_content


def test_normalize_chunk_content_handles_list_text():
    chunk = AIMessageChunk(
        content=[{"type": "text", "text": "hello"}],
        response_metadata={"model_provider": "google_genai"},
    )
    assert GenericLangGraphChatAgent._normalize_chunk_content(chunk) == "hello"


@pytest.mark.asyncio
async def test_active_skill_injected_into_system_messages():
    agent = build_agent_with_skills()
    agent._active_skill_state.mark_loaded("sql", "use the skill")
    inputs = await agent._build_stream_inputs("hello", "session-1")
    system_messages = [m for m in inputs["messages"] if m["role"] == "system"]
    assert any("use the skill" in m["content"] for m in system_messages)
    assert system_messages[0]["role"] == "system"
    assert "use the skill" in system_messages[0]["content"]


@pytest.mark.asyncio
async def test_active_skill_system_message_precedes_context():
    agent = build_agent_with_skills()
    agent._active_skill_state.mark_loaded("sql", "use the skill")
    agent.retriever = DummyRetriever()
    agent.memory_manager = DummyMemoryManager()
    inputs = await agent._build_stream_inputs("hello", "session-1")
    system_messages = [m for m in inputs["messages"] if m["role"] == "system"]
    assert "use the skill" in system_messages[0]["content"]
    assert "retrieved context" in system_messages[1]["content"]


@pytest.mark.asyncio
async def test_no_active_skill_message_when_unset():
    agent = build_agent_with_skills()
    inputs = await agent._build_stream_inputs("hello", "session-1")
    system_messages = [m for m in inputs["messages"] if m["role"] == "system"]
    assert not any("ACTIVE SKILL" in m["content"] for m in system_messages)


def test_capture_skill_tool_output_sets_state():
    agent = build_agent_with_skills()
    tool_message = ToolMessage(content="skill text", name="load_skill", tool_call_id="1")
    agent._capture_skill_tool_outputs({"messages": [tool_message]})
    assert agent._get_active_skill_text_for_testing() == "skill text"


@pytest.mark.asyncio
async def test_forward_subagent_events_emits_text():
    agent = build_agent()
    subagent_queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
    output_queue: asyncio.Queue = asyncio.Queue()

    task = asyncio.create_task(agent._forward_subagent_events(subagent_queue, output_queue))
    event = StreamEvent(source="subagent:test", type="text", content="hello", metadata={"final": True})
    await subagent_queue.put(event)

    item = await asyncio.wait_for(output_queue.get(), timeout=1)
    task.cancel()
    assert item["response_type"] == "text"
    assert "(final)" in item["content"]


@pytest.mark.asyncio
async def test_emit_final_output_emits_data_for_json_artifact():
    agent = build_agent()
    output_queue: asyncio.Queue = asyncio.Queue()
    accumulator = AIMessageAccumulator()

    accumulator.add_chunk(
        AIMessageChunk(content=f"{ARTIFACT_START}{{\"foo\": \"bar\"}}{ARTIFACT_END}")
    )

    await agent._emit_final_output(output_queue, accumulator, "session-1", "task-1")
    item = await asyncio.wait_for(output_queue.get(), timeout=1)

    assert item["response_type"] == "data"
    assert item["content"] == {"foo": "bar"}
