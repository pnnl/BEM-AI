# Server-backed Sim Chat Demo

This example starts a local MCP weather server and an A2A agent server. The
Streamlit UI connects to the A2A server over HTTP.

```bash
uv sync --extra sim_chat_server_demo
```

Set `CHATBOT_SERVER_URL` in `.env` to the A2A server URL, then use two terminals:

```bash
python examples/sim_chat_server_demo/chatbot.py
```

```bash
streamlit run examples/sim_chat_server_demo/streamlit_ui.py
```

The runtime path is: browser → Streamlit → A2A server → agent → MCP/Ollama.
