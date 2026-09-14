from __future__ import annotations

import asyncio
import uuid

import streamlit as st

from examples.sim_chat_demo.chatbot import build_chatbot


@st.cache_resource
def get_chatbot():
    return build_chatbot()


def get_session_id() -> str:
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = str(uuid.uuid4())
    return st.session_state["session_id"]


async def stream_reply(prompt: str, session_id: str):
    task_id = str(uuid.uuid4())
    async for chunk in get_chatbot().stream(prompt, session_id, task_id):
        content = chunk.get("content")
        if content:
            yield content


def main() -> None:
    st.set_page_config(page_title="Automa AI Chat", page_icon="💬", layout="centered")
    st.title("💬 Automa AI Chat")
    st.caption("A standalone YAML-defined agent; no local agent server is required.")
    session_id = get_session_id()
    st.session_state.setdefault("messages", [])

    for message in st.session_state["messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("Type your message..."):
        st.session_state["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            placeholder = st.empty()
            response = ""

            async def consume() -> None:
                nonlocal response
                async for text in stream_reply(prompt, session_id):
                    response += text
                    placeholder.markdown(response + "▌")

            asyncio.run(consume())
            placeholder.markdown(response)
        st.session_state["messages"].append({"role": "assistant", "content": response})


if __name__ == "__main__":
    main()
