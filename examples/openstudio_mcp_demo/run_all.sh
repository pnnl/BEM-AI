#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_SCRIPT="$SCRIPT_DIR/agent.py"
CLIENT_SCRIPT="$SCRIPT_DIR/ui.py"
LOG_DIR="$SCRIPT_DIR/logs"
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

trap cleanup SIGINT SIGTERM EXIT
while kill -0 "$SERVER_PID" 2>/dev/null && kill -0 "$CLIENT_PID" 2>/dev/null; do
  sleep 1
done
