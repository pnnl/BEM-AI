from automa_ai.config.agent_spec import YamlAgentSpec
from examples.sim_chat_demo import chatbot as demo
from examples.sim_chat_demo import streamlit_ui
import pytest


def test_sim_chat_demo_is_a_standalone_yaml_agent() -> None:
    spec = YamlAgentSpec.from_yaml_file(demo.SPEC_PATH)

    assert spec.agent is not None
    assert spec.agent_card is None
    assert spec.a2a is None
    assert spec.mcp is None
    assert spec.to_factory_kwargs()["tools_config"] == {
        "tools": [{"type": "web_search", "config": {"provider": "opensource"}}]
    }


@pytest.mark.asyncio
async def test_sim_chat_demo_replaces_streamed_text_with_terminal_response(monkeypatch) -> None:
    class FakeChatbot:
        async def stream(self, *_args):
            yield {"content": "Hel", "is_task_complete": False}
            yield {"content": "lo", "is_task_complete": False}
            yield {"content": "Hello", "is_task_complete": True}

    monkeypatch.setattr(streamlit_ui, "get_chatbot", lambda: FakeChatbot())

    updates = [update async for update in streamlit_ui.stream_reply("hello", "session")]
    response = ""
    for text, is_complete in updates:
        response = text if is_complete else response + text

    assert response == "Hello"
