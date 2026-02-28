#!/bin/bash
set -e

SERVER_SCRIPT="agent.py"
CLIENT_SCRIPT="ui.py"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

python3 "$SERVER_SCRIPT" > "$LOG_DIR/server.log" 2>&1 &
SERVER_PID=$!

MAX_WAIT=60
WAITED=0
until grep -q "✅ A2A Server started" "$LOG_DIR/server.log" 2>/dev/null; do
  sleep 1
  WAITED=$((WAITED + 1))
  if [ "$WAITED" -ge "$MAX_WAIT" ]; then
    echo "Server startup timed out"
    kill $SERVER_PID 2>/dev/null || true
    exit 1
  fi
done

streamlit run "$CLIENT_SCRIPT" > "$LOG_DIR/client.log" 2>&1 &
CLIENT_PID=$!

echo "Server PID: $SERVER_PID"
echo "Client PID: $CLIENT_PID"

cleanup() {
  kill $CLIENT_PID 2>/dev/null || true
  kill $SERVER_PID 2>/dev/null || true
}

trap cleanup SIGINT
while true; do sleep 1; done
