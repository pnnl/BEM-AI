import asyncio
import streamlit as st
from automa_ai.client.simple_client import SimpleClient  # assuming your file is named simple_client.py

A2A_SERVER_URL = "http://localhost:9999"

# Cache the client instance
@st.cache_resource
def get_client():
    return SimpleClient(agent_url=A2A_SERVER_URL)

async def send_message_async(user_message: str):
    client = get_client()
    response_chunks = []
    async for chunk in client.send_streaming_message(user_message):
        response_chunks.append(chunk)
        yield chunk

def main():
    st.set_page_config(page_title="A2A Chat", page_icon="💬", layout="centered")
    st.title("💬 A2A Chat Interface")

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
                    async for chunk in send_message_async(prompt):
                        text_part = None
                        if isinstance(chunk, dict) and "result" in chunk:
                            result = chunk.get("result", {})
                            status = result.get("status", {})
                            message = status.get("message", {})
                            parts = message.get("parts", [])
                            text_fragments = [
                                p.get("text") for p in parts if p.get("kind") == "text" and p.get("text")
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
                            full_response += text_part
                            message_placeholder.markdown(full_response + "▌")

                    message_placeholder.markdown(full_response)

            asyncio.run(process_stream())

        st.session_state["messages"].append(
            {"role": "assistant", "content": full_response}
        )

if __name__ == "__main__":
    main()