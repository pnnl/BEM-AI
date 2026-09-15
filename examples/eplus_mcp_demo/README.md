# 💬 EnergyPlus MCP Chatbot (A2A + Streamlit Client)

This project provides an **integration of AUTOMA-AI Agent with EnergyPlus MCP demo** consisting of two parts:

1. **Server** — an async A2A chatbot backend (supports JSON-RPC). 
2. **EnergyPlus MCP** - a MCP server developed by [LBNL](https://github.com/LBNL-ETA/EnergyPlus-MCP/tree/main/energyplus-mcp-server/energyplus_mcp_server). The script is slightly modified to accommodate AUTOMA-AI client interface.
2. **Client** — a Streamlit-based chat UI built with React-style components and streaming support.

The client communicates with the server in real time, displaying streamed model responses as they arrive.

---

## 🚀 Features

- **Real-time chat** over SSE transport  
- **JSON-RPC compatible** message format  
- **Async server** built with `asyncio`  
- **Streamlit chat UI** with incremental message streaming  
- **Auto-launch script** to start both server and client  

---

## 🧩 Project Structure

```
.
├── eplus_chatbot.py          # A2A async server implementation
├── ui.py                     # Streamlit chat UI
├── run_all.sh                # Helper script to start both server & client
├── energyplus_mcp_server     # MCP server scripts
├── log                 # log folder (auto-generated)
    ├── server.log          # Server log (auto-generated)
    └── client.log          # Client log (auto-generated)
└── README.md
```

---

## ⚙️ Prerequisites

Make sure you have the following installed:

- **Python 3.10+**
- **Streamlit**
- **automa_ai 0.2.0**
- **Async libraries**
- **plotly**
- **matplotlib**
- **eppy**

To install dependencies:

```bash
pip install -r requirements.txt
```

Example `requirements.txt`:
```txt
streamlit
automa_ai
plotly
matplotlib
eppy
```

Or run
```bash
pip install automa_ai[eplus_mcp_demo]
```

## Preparation
### Update local env file
Create a `.env` file in the root folder, using the [example.env](./example.env) as an example to specify language models, API keys, URLs.


---

## ▶️ How to Run

### Option 1: Run both (recommended)
Use the provided shell script to start both server and Streamlit client together:

```bash
chmod +x run_all.sh
./run_all.sh
```
<div class="warning">
  <strong>WARNING:</strong> This approach is unstable. It is recommended running server and client separately for now.
</div>


This will:
- Start the chatbot server on `http://localhost:9999`
- Wait a few seconds
- Launch the Streamlit chat UI on `http://localhost:8501`

> Press **Ctrl+C** to stop both processes cleanly.

---

### Option 2: Run manually

#### 1️⃣ Start the server
```bash
python energyplus_bot.py
```

Once you see:
```
✅ A2A Server started at http://localhost:9999/
```

#### 2️⃣ In a new terminal, start the client
```bash
streamlit run client.py
```

---

## 💻 Access the Chatbot

After starting, open your browser and go to:

👉 [http://localhost:8501](http://localhost:8501)

You should see the Streamlit-based chat interface.  
Type a message and watch the assistant stream its response in real time.

---

## 🧹 Stopping the App

Press **Ctrl+C** in the terminal where you ran `run_all.sh`.  
Both the server and Streamlit client will shut down gracefully.

---

## 🧠 Notes

- The architecture is designed to be **agent-ready**, compatible with **A2A JSON-RPC servers**.  
- You can modify the server endpoint in `ui.py` if needed.  
- The server can later be extended to handle multiple clients, persistent sessions, or multi-agent workflows.
