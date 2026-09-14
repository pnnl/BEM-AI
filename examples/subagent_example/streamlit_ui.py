import asyncio
import os
import uuid
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from automa_ai.client.simple_client import (
    SimpleClient,
)  # assuming your file is named simple_client.py
from automa_ai.client.ui_util import extract_stream_text, natural_delay


# Cache the client instance
@st.cache_resource
def get_client():
    return SimpleClient(agent_url="http://localhost:30000")


# ---------------------------------------------------------------------
# Create/get a session ID
# ---------------------------------------------------------------------
def get_session_id():
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = str(uuid.uuid4())
    return st.session_state["session_id"]


async def send_message_async(user_message: str, session_id: str):
    client = get_client()
    response_chunks = []
    async for chunk in client.send_streaming_message(user_message, session_id):
        response_chunks.append(chunk)
        yield chunk


def main():
    st.set_page_config(page_title="Subagent Example Chat", page_icon="💬", layout="centered")
    st.title("💬 Subagent Example Interface")

    # Initialize session ID
    session_id = get_session_id()

    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    # Display chat history
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    if prompt := st.chat_input("Type your message..."):
        st.session_state["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Streaming assistant response
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            full_response = ""

            async def process_stream():
                nonlocal full_response
                with st.spinner("🤖 Thinking..."):
                    async for chunk in send_message_async(prompt, session_id):
                        update = extract_stream_text(chunk)
                        if update.text:
                            if update.is_final:
                                full_response = update.text
                            else:
                                await natural_delay(update.text)
                                full_response += update.text
                            message_placeholder.markdown(full_response + "▌")

                    message_placeholder.markdown(full_response)

            asyncio.run(process_stream())

        st.session_state["messages"].append(
            {"role": "assistant", "content": full_response}
        )


if __name__ == "__main__":
    main()
