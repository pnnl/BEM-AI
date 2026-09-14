import asyncio
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from automa_ai.client.simple_client import (
    SimpleClient,
)
from automa_ai.client.ui_util import extract_stream_text


base_dir = Path(__file__).resolve().parent
env_path = base_dir / '.env'
load_dotenv(dotenv_path=env_path)

A2A_SERVER_URL = os.getenv("CHATBOT_SERVER_URL")


# Cache the client instance
@st.cache_resource
def get_client():
    return SimpleClient(agent_url=A2A_SERVER_URL)

async def send_message_async(user_message: str, context_id: str | None = None):
    client = get_client()
    response_chunks = []
    async for chunk in client.send_streaming_message(user_message, context_id):
        response_chunks.append(chunk)
        yield chunk


def main():
    st.set_page_config(page_title="EnergyPlus AI Chat", page_icon="💬", layout="centered")
    st.title("💬 EnergyPlus AI Chat Interface")

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
                    async for chunk in send_message_async(prompt, st.session_state.get("context_id")):
                        if isinstance(chunk, dict) and "result" in chunk:
                            result = chunk.get("result", {})
                            context_id = result.get("contextId")
                            if context_id:
                                st.session_state["context_id"] = context_id

                        update = extract_stream_text(chunk)
                        if update.state == "input-required":
                            st.session_state["awaiting_input"] = True
                            full_response += (
                                "\n\n🟡 *Agent is waiting for your response...*\n\n"
                                f"**Response:** {update.text}"
                            )
                            message_placeholder.markdown(full_response)
                            break

                        st.session_state["awaiting_input"] = False
                        if update.text:
                            full_response = update.text if update.replaces_text else full_response + update.text
                            message_placeholder.markdown(full_response + "▌")

            asyncio.run(process_stream())

        st.session_state["messages"].append(
            {"role": "assistant", "content": full_response}
        )

if __name__ == "__main__":
    main()
