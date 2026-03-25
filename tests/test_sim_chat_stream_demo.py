from examples.sim_chat_stream_demo import chatbot as demo


def test_sim_chat_stream_demo_enables_opensource_web_search() -> None:
    tools_config = demo.chatbot.tools_config

    assert tools_config is not None
    assert tools_config["tools"][0]["type"] == "web_search"
    assert tools_config["tools"][0]["config"]["provider"] == "opensource"
