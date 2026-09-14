from __future__ import annotations

import asyncio
import uuid
from queue import Queue
from threading import Thread
from typing import Iterator

import streamlit as st

from examples.sim_chat_demo.chatbot import build_chatbot


class ChatbotRuntime:
    """Run the cached memory-enabled agent on one dedicated event loop."""

    def __init__(self) -> None:
        self.agent = build_chatbot()
        self._loop = asyncio.new_event_loop()
        self._thread = Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._closed = False

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def stream(self, prompt: str, session_id: str) -> Iterator[tuple[str, bool]]:
        events: Queue[tuple[str, bool] | BaseException | None] = Queue()
        task_id = str(uuid.uuid4())

        async def consume() -> None:
            try:
                async for chunk in self.agent.stream(prompt, session_id, task_id):
                    content = chunk.get("content")
                    if content:
                        events.put((content, bool(chunk.get("is_task_complete"))))
            except BaseException as exc:
                events.put(exc)
            finally:
                events.put(None)

        future = asyncio.run_coroutine_threadsafe(consume(), self._loop)
        while True:
            event = events.get()
            if event is None:
                future.result()
                return
            if isinstance(event, BaseException):
                future.result()
                raise event
            yield event

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            asyncio.run_coroutine_threadsafe(self.agent.aclose(), self._loop).result()
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)


@st.cache_resource
def get_chatbot():
    return ChatbotRuntime()


def get_session_id() -> str:
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = str(uuid.uuid4())
    return st.session_state["session_id"]


def stream_reply(prompt: str, session_id: str) -> Iterator[tuple[str, bool]]:
    yield from get_chatbot().stream(prompt, session_id)


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

            for text, is_complete in stream_reply(prompt, session_id):
                response = text if is_complete else response + text
                placeholder.markdown(response + "▌")
            placeholder.markdown(response)
        st.session_state["messages"].append({"role": "assistant", "content": response})


if __name__ == "__main__":
    main()
