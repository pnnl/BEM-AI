# Standalone Sim Chat Demo

This example runs the YAML-defined agent inside the Streamlit process. It does
not start or connect to an A2A or MCP server.

```bash
uv sync --extra sim_chat_demo
streamlit run examples/sim_chat_demo/streamlit_ui.py
```

Optionally copy `example.env` to `.env` and select an Ollama model and base URL.
The app defaults to `llama3.3:70b` and `http://localhost:11434`.

The runtime path is: browser → Streamlit → in-process agent → Ollama.
