# Feishu / Lark Setup

This example shows how to connect a Feishu (Lark) bot to any A2A-compatible entry agent using the inbound long-connection gateway.

The gateway is intentionally decoupled from any specific A2A network. It forwards Feishu chat messages to whatever agent URL you configure, making it reusable across different examples (e.g. `sim_bem_network`).

## Prerequisites

- A Feishu app with **bot** capabilities enabled and the `im:message:receive_v1` event subscription.
- The official Lark SDK: `pip install lark-oapi`
- An A2A entry agent running and reachable at `FEISHU_ENTRY_AGENT_URL`.

## Configuration

Copy `example.env` to `.env` and fill in the required values:

| Variable | Required | Description |
|---|---|---|
| `FEISHU_APP_ID` | yes | Feishu app ID |
| `FEISHU_APP_SECRET` | yes | Feishu app secret |
| `FEISHU_ENTRY_AGENT_URL` | yes | URL of the A2A entry agent (default: `http://localhost:10001`) |
| `FEISHU_SESSION_STORE_PATH` | no | Path to persist chat→session mapping (default: `feishu_sessions.json` next to this file) |
| `FEISHU_ENABLED` | no | Set to `true` to enable outbound webhook push cards |
| `FEISHU_WEBHOOK_DEFAULT` | no | Default outbound webhook URL for push notifications |
| `FEISHU_WEBHOOK_ORCHESTRATOR` | no | Per-agent webhook override |
| `FEISHU_WEBHOOK_PLANNER` | no | Per-agent webhook override |
| `FEISHU_WEBHOOK_SIMULATION` | no | Per-agent webhook override |
| `FEISHU_WEBHOOK_OUTPUT` | no | Per-agent webhook override |
| `FEISHU_WEBHOOK_SECRET` | no | HMAC signing secret for outbound webhooks |
| `FEISHU_TIMEZONE` | no | Display timezone for push card timestamps (default: `Asia/Shanghai`) |

## Running the gateway

```bash
# Install dependencies (lark-oapi is in the sim_bem_network extras as well)
pip install lark-oapi

# Start the gateway
python feishu_gateway.py
```

The gateway opens a persistent WebSocket connection to Feishu. When a user sends a message to your bot, the gateway:

1. Deduplicates and extracts the plain text (strips `@mention` tokens).
2. Looks up or creates a per-chat A2A `contextId` in `feishu_sessions.json`.
3. Forwards the message to the entry agent via `SimpleClient.send_streaming_message`.
4. Persists the returned `contextId` so subsequent messages in the same chat continue the session.

## Outbound notifications

Independently of the inbound gateway, the `automa_ai.observability` package provides `FeishuWebhookNotifier` and `FeishuWebhookRouter`. These are wired into the orchestrator via `create_feishu_notifier_from_env()` and push Feishu interactive cards at key workflow events (session start, planner tasks, blackboard updates, completion). Set `FEISHU_ENABLED=true` and provide webhook URLs to activate them.
