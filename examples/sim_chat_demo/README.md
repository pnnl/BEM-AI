# 💬 Automa_AI Chatbot (WebSocket + Streamlit Client)

This project provides a **simple AI chatbot demo** consisting of two parts:

1. **Server** — an async A2A chatbot backend (supports JSON-RPC).  
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
├── chatbot.py          # A2A async server implementation
├── streamlit_ui.py     # Streamlit chat UI
├── run_all.sh          # Helper script to start both server & client
├── log                 # log folder (auto-generated)
    ├── server.log          # Server log (auto-generated)
    └── client.log          # Client log (auto-generated)
└── README.md
```

---

## ⚙️ Prerequisites

Make sure you have the following installed:

- **Python 3.12+**
- **Streamlit**
- **automa_ai 0.1.2**
- **Async libraries** used in your chatbot (e.g. `httpx`, etc.)

To install dependencies:

```bash
pip install -r requirements.txt
```

Example `requirements.txt`:
```txt
streamlit
automa_ai
```

---

## ▶️ How to Run

### Option 1: Run both (recommended)
Use the provided shell script to start both server and Streamlit client together:

```bash
chmod +x run_all.sh
./run_all.sh
```

This will:
- Start the chatbot server on `http://localhost:9999`
- Wait a few seconds
- Launch the Streamlit chat UI on `http://localhost:8501`

> Press **Ctrl+C** to stop both processes cleanly.

---

### Option 2: Run manually

#### 1️⃣ Start the server
```bash
python chatbot.py
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
- You can modify the server endpoint in `streamlit_ui.py` if needed.  
- The server can later be extended to handle multiple clients, persistent sessions, or multi-agent workflows.