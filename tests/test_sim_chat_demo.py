import asyncio

from automa_ai.config.agent_spec import YamlAgentSpec
from examples.sim_chat_demo import chatbot as demo
from examples.sim_chat_demo import streamlit_ui


def test_sim_chat_demo_is_a_standalone_yaml_agent() -> None:
    spec = YamlAgentSpec.from_yaml_file(demo.SPEC_PATH)

    assert spec.agent is not None
    assert spec.agent_card is None
    assert spec.a2a is None
    assert spec.mcp is None
    assert spec.to_factory_kwargs()["tools_config"] == {
        "tools": [{"type": "web_search", "config": {"provider": "opensource"}}]
    }


def test_sim_chat_demo_replaces_streamed_text_with_terminal_response(monkeypatch) -> None:
    class FakeRuntime:
        def stream(self, *_args):
            yield "Hel", False
            yield "lo", False
            yield "Hello", True

    monkeypatch.setattr(streamlit_ui, "get_chatbot", lambda: FakeRuntime())

    updates = list(streamlit_ui.stream_reply("hello", "session"))
    response = ""
    for text, is_complete in updates:
        response = text if is_complete else response + text

    assert response == "Hello"


def test_sim_chat_demo_reuses_one_loop_for_cached_runtime(monkeypatch) -> None:
    loop_ids: list[int] = []

    class FakeAgent:
        async def stream(self, *_args):
            loop_ids.append(id(asyncio.get_running_loop()))
            yield {"content": "done", "is_task_complete": True}

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(streamlit_ui, "build_chatbot", FakeAgent)
    runtime = streamlit_ui.ChatbotRuntime()
    try:
        assert list(runtime.stream("one", "session")) == [("done", True)]
        assert list(runtime.stream("two", "session")) == [("done", True)]
    finally:
        runtime.close()

    assert len(set(loop_ids)) == 1
