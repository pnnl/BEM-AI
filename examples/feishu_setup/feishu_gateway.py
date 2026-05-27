"""Feishu inbound gateway for the sim_bem_network orchestrator.

This gateway is intentionally separate from the A2A network process. It listens
for Feishu/Lark bot message events via the official long-connection SDK, then
forwards user text to the existing A2A entry agent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from automa_ai.client.simple_client import SimpleClient

logger = logging.getLogger(__name__)

base_dir = Path(__file__).resolve().parent
load_dotenv(dotenv_path=base_dir / ".env")

ENTRY_AGENT_URL = os.getenv("FEISHU_ENTRY_AGENT_URL", "http://localhost:10001")
SESSION_STORE_PATH = Path(
    os.getenv("FEISHU_SESSION_STORE_PATH", base_dir / "feishu_sessions.json")
)

_worker_loop = asyncio.new_event_loop()


def _start_worker_loop() -> None:
    asyncio.set_event_loop(_worker_loop)
    _worker_loop.run_forever()


_worker_thread = threading.Thread(
    target=_start_worker_loop,
    name="feishu-gateway-a2a-worker",
    daemon=True,
)
_worker_thread.start()
_processed_message_ids: set[str] = set()
_active_chat_keys: set[str] = set()


def _load_sessions() -> dict[str, str]:
    if not SESSION_STORE_PATH.exists():
        return {}
    try:
        return json.loads(SESSION_STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load Feishu session store.")
        return {}


def _save_sessions(sessions: dict[str, str]) -> None:
    SESSION_STORE_PATH.write_text(
        json.dumps(sessions, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _message_key(event: Any) -> str:
    message = event.event.message
    chat_id = getattr(message, "chat_id", None) or "unknown-chat"
    return chat_id


def _message_id(event: Any) -> str | None:
    message = event.event.message
    return getattr(message, "message_id", None) or getattr(message, "messageId", None)


def _extract_text(event: Any) -> str:
    message = event.event.message
    raw_content = getattr(message, "content", "") or ""
    try:
        content = json.loads(raw_content)
        text = content.get("text") or ""
    except Exception:
        text = raw_content

    # Feishu mention tokens often appear as <at user_id="...">name</at>.
    text = re.sub(r"<at[^>]*>.*?</at>", "", text).strip()
    # Some SDK/rendering paths normalize mentions into @_user_1-style tokens.
    text = re.sub(r"@\S+", "", text).strip()
    return text


def _is_from_bot(event: Any) -> bool:
    sender = getattr(event.event, "sender", None)
    sender_type = getattr(sender, "sender_type", "") if sender else ""
    return sender_type == "bot"


async def _forward_to_orchestrator(text: str, chat_key: str) -> None:
    sessions = _load_sessions()
    context_id = sessions.get(chat_key)

    client = SimpleClient(agent_url=ENTRY_AGENT_URL, timeout=None)
    latest_context_id = context_id
    async for chunk in client.send_streaming_message(text, context_id=context_id):
        result = chunk.get("result", {}) if isinstance(chunk, dict) else {}
        latest_context_id = result.get("contextId") or latest_context_id
        logger.info("A2A gateway chunk: %s", chunk)

    if latest_context_id:
        sessions[chat_key] = latest_context_id
        _save_sessions(sessions)


def _handle_message_event(event: Any) -> None:
    if _is_from_bot(event):
        return

    message_id = _message_id(event)
    if message_id and message_id in _processed_message_ids:
        logger.info("Ignoring duplicate Feishu message event: %s", message_id)
        return

    text = _extract_text(event)
    if not text:
        logger.info("Ignoring empty Feishu message event.")
        return

    chat_key = _message_key(event)
    if chat_key in _active_chat_keys:
        logger.info(
            "Ignoring Feishu message while chat %s already has an active A2A request: %s",
            chat_key,
            text,
        )
        return

    if message_id:
        _processed_message_ids.add(message_id)
    _active_chat_keys.add(chat_key)
    logger.info("Forwarding Feishu message from %s to %s: %s", chat_key, ENTRY_AGENT_URL, text)
    future = asyncio.run_coroutine_threadsafe(
        _forward_to_orchestrator(text, chat_key),
        _worker_loop,
    )

    def _on_done(done_future) -> None:
        _active_chat_keys.discard(chat_key)
        try:
            done_future.result()
        except Exception:
            logger.exception("Failed to forward Feishu message to A2A orchestrator.")

    future.add_done_callback(_on_done)


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise RuntimeError(
            "FEISHU_APP_ID and FEISHU_APP_SECRET are required for the inbound gateway."
        )

    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
    except ImportError as exc:
        raise RuntimeError(
            "The Feishu inbound gateway requires the official SDK. Install it with: "
            "pip install lark-oapi"
        ) from exc

    def on_message(data: P2ImMessageReceiveV1) -> None:
        _handle_message_event(data)

    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .build()
    )

    ws_client = lark.ws.Client(
        app_id=app_id,
        app_secret=app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )

    logger.info("Starting Feishu inbound gateway for %s", ENTRY_AGENT_URL)
    ws_client.start()


if __name__ == "__main__":
    main()
