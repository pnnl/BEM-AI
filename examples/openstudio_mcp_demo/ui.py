import asyncio
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from automa_ai.client.simple_client import SimpleClient

base_dir = Path(__file__).resolve().parent
env_path = base_dir / ".env"
load_dotenv(dotenv_path=env_path)

A2A_SERVER_URL = os.getenv("CHATBOT_SERVER_URL", "http://localhost:9999")


@st.cache_resource
def get_client() -> SimpleClient:
    return SimpleClient(agent_url=A2A_SERVER_URL)


async def send_message_async(user_message: str, context_id: str | None = None):
    client = get_client()
    async for chunk in client.send_streaming_message(user_message, context_id):
        yield chunk


def main() -> None:
    st.set_page_config(page_title="OpenStudio MCP Demo", page_icon="🏗️", layout="centered")
    st.title("🏗️ OpenStudio MCP Sizing Demo")

    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask for an HVAC sizing workflow..."):
        st.session_state["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            placeholder = st.empty()
            response_text = ""

            async def process_stream():
                nonlocal response_text
                async for chunk in send_message_async(prompt, st.session_state.get("context_id")):
                    text_part = chunk.get("content") if isinstance(chunk, dict) else None
                    if text_part:
                        response_text += str(text_part)
                        placeholder.markdown(response_text + "▌")

            asyncio.run(process_stream())
            placeholder.markdown(response_text)

        st.session_state["messages"].append({"role": "assistant", "content": response_text})


if __name__ == "__main__":
    main()
