#!/bin/bash
# ===============================
# Run A2A chatbot server + client
# ===============================

# How to run this script:
# chmod +x run_all.sh
# ./run_all.sh

# Exit on error
set -e

SERVER_SCRIPT="sim_bem_network_orchestrator.py"
CLIENT_SCRIPT="streamlit_ui.py"
STREAMLIT_PORT=8501
LOG_DIR="logs"

mkdir -p "$LOG_DIR"

echo "🔧 Starting A2A Server..."
python "$SERVER_SCRIPT" > "$LOG_DIR/server.log" 2>&1 &
SERVER_PID=$!

echo "🌐 Waiting for server to start..."
MAX_WAIT=90
WAITED=0

# Wait until server prints "✅ A2A Server started"
until grep -q "✅ A2A Server started" "$LOG_DIR/server.log" 2>/dev/null; do
    sleep 1
    WAITED=$((WAITED + 1))
    if [ "$WAITED" -ge "$MAX_WAIT" ]; then
        echo "❌ Timeout waiting for server startup (>${MAX_WAIT}s)"
        echo "Check logs/server.log for details."
        kill $SERVER_PID 2>/dev/null || true
        exit 1
    fi
    echo "   ... waiting ($WAITED s)"
done

echo "✅ Server is up!"

# Wait a few seconds for the server to complete initialization
sleep 5

echo "🚀 Starting Streamlit client..."
streamlit run "$CLIENT_SCRIPT" > "$LOG_DIR/client.log" 2>&1 &
CLIENT_PID=$!

echo ""
echo "✅ Both processes running:"
echo "   - Server PID: $SERVER_PID (http://localhost:10001)"
echo "   - Client PID: $CLIENT_PID (http://localhost:$STREAMLIT_PORT)"
echo ""
echo "🧭 Logs:"
echo "   - Server: $LOG_DIR/server.log"
echo "   - Client: $LOG_DIR/client.log"
echo ""
echo "💡 Press Ctrl+C to stop both."

cleanup() {
    echo ""
    echo "🛑 Stopping both processes..."
    kill $CLIENT_PID 2>/dev/null || true
    kill $SERVER_PID 2>/dev/null || true
    wait $CLIENT_PID 2>/dev/null || true
    wait $SERVER_PID 2>/dev/null || true
    echo "✅ All processes stopped."
    exit 0
}

trap cleanup SIGINT

# Keep alive until Ctrl+C
while true; do
    sleep 1
done
