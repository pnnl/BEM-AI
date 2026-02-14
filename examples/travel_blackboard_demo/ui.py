from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import streamlit as st

from automa_ai.client.simple_client import SimpleClient
from examples.travel_blackboard_demo.agents.common import blackboard_file_path

BASE_DIR = Path(__file__).resolve().parent
BLACKBOARD_BASE_DIR = BASE_DIR / ".demo_blackboards"
ORCHESTRATOR_URL = os.getenv("TRAVEL_ORCHESTRATOR_URL", "http://localhost:33000")


@st.cache_resource
def get_client() -> SimpleClient:
    return SimpleClient(agent_url=ORCHESTRATOR_URL, timeout=60)


def get_session_id() -> str:
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = str(uuid.uuid4())
    return st.session_state["session_id"]


def blackboard_read(session_id: str) -> dict:
    path = blackboard_file_path(BLACKBOARD_BASE_DIR, session_id)
    if not path.exists():
        return {"message": "No blackboard document found for this session yet."}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "session_id": session_id,
        "revision": data.get("revision"),
        "updated_at": data.get("updated_at"),
        "data": data.get("data", {}),
    }


async def stream_reply(prompt: str, session_id: str):
    client = get_client()
    async for chunk in client.send_streaming_message(prompt, session_id):
        text_part = None
        if isinstance(chunk, dict) and "result" in chunk:
            result = chunk.get("result", {})
            status = result.get("status", {})
            message = status.get("message", {})
            parts = message.get("parts", [])
            text_fragments = [
                p.get("text")
                for p in parts
                if p.get("kind") == "text" and p.get("text")
            ]
            if text_fragments:
                text_part = "\n".join(text_fragments)
        elif "delta" in chunk and "text" in chunk["delta"]:
            text_part = chunk["delta"]["text"]
        elif "message" in chunk and "text" in chunk["message"]:
            text_part = chunk["message"]["text"]
        elif "content" in chunk:
            text_part = chunk["content"]
        elif "data" in chunk:
            text_part = chunk["data"]

        if text_part:
            yield text_part


def main() -> None:
    st.set_page_config(page_title="Travel Blackboard Demo", page_icon="✈️", layout="wide")
    st.title("✈️ Travel Booking Blackboard Demo")
    st.caption("LangGraph chat agents via AgentFactory with shared blackboard orchestration.")

    session_id = get_session_id()
    with st.sidebar:
        st.subheader("Session")
        st.text_input("Session ID", key="session_id")
        if st.button("New Session"):
            st.session_state["session_id"] = str(uuid.uuid4())
            st.rerun()
        st.write(f"Orchestrator URL: `{ORCHESTRATOR_URL}`")

        if st.button("Refresh Blackboard Snapshot"):
            st.session_state["bb_snapshot"] = blackboard_read(st.session_state["session_id"])

        with st.expander("Blackboard Snapshot", expanded=False):
            snapshot = st.session_state.get("bb_snapshot", blackboard_read(session_id))
            st.json(snapshot)

    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    for message in st.session_state["messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("Ask the orchestrator to plan and book your trip..."):
        st.session_state["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            placeholder = st.empty()
            full_reply = ""

            async def consume_stream():
                nonlocal full_reply
                async for token in stream_reply(prompt, st.session_state["session_id"]):
                    full_reply += token
                    placeholder.markdown(full_reply + "▌")
                placeholder.markdown(full_reply)

            asyncio.run(consume_stream())

        st.session_state["messages"].append({"role": "assistant", "content": full_reply})
        st.session_state["bb_snapshot"] = blackboard_read(st.session_state["session_id"])


if __name__ == "__main__":
    main()
