import asyncio
import html
import os
import re
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from automa_ai.client.simple_client import SimpleClient

base_dir = Path(__file__).resolve().parent
env_path = base_dir / ".env"
load_dotenv(dotenv_path=env_path)

A2A_SERVER_URL = os.getenv("CHATBOT_SERVER_URL", "http://localhost:9999")
LOAD_SKILL_STATUS_RE = re.compile(
    r"\btool\s+load_skill\s+responded:\s*", re.IGNORECASE
)
LOAD_SKILL_ERROR_MARKERS = (
    "error",
    "exception",
    "traceback",
    "failed",
    "failure",
)


STATUS_PANEL_CSS = """
<style>
.openstudio-status-panel {
    background: #f4f5f7;
    border: 1px solid #e1e4e8;
    border-radius: 6px;
    color: #4b5563;
    font-size: 0.82rem;
    line-height: 1.35;
    margin: 0.25rem 0 0.75rem;
    padding: 0.65rem 0.75rem;
}
.openstudio-status-panel summary {
    cursor: pointer;
    list-style: none;
}
.openstudio-status-panel summary::-webkit-details-marker {
    display: none;
}
.openstudio-status-panel-title {
    color: #374151;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.03em;
    margin-bottom: 0;
    text-transform: uppercase;
}
.openstudio-status-panel-title::before {
    content: "▸";
    display: inline-block;
    margin-right: 0.35rem;
}
.openstudio-status-panel[open] .openstudio-status-panel-title {
    margin-bottom: 0.35rem;
}
.openstudio-status-panel[open] .openstudio-status-panel-title::before {
    content: "▾";
}
.openstudio-status-body {
    overflow-wrap: anywhere;
    white-space: pre-line;
}
.openstudio-artifact-title {
    color: #374151;
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0.03em;
    margin: 0.4rem 0 0.25rem;
    text-transform: uppercase;
}
</style>
"""


@st.cache_resource
def get_client() -> SimpleClient:
    return SimpleClient(agent_url=A2A_SERVER_URL)


async def send_message_async(user_message: str, context_id: str | None = None):
    client = get_client()
    async for chunk in client.send_streaming_message(user_message, context_id):
        yield chunk


def _extract_text_from_parts(parts: list[dict[str, Any]]) -> str | None:
    text_fragments = [
        part["text"]
        for part in parts
        if part.get("kind") == "text" and part.get("text")
    ]
    return "\n".join(text_fragments) if text_fragments else None


def _extract_data_from_parts(parts: list[dict[str, Any]]) -> list[Any]:
    return [
        part["data"]
        for part in parts
        if part.get("kind") == "data" and "data" in part
    ]


def _parse_stream_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    """Normalize A2A stream chunks into UI event types."""
    if isinstance(chunk, dict) and "result" in chunk:
        result = chunk.get("result", {})
        kind = result.get("kind")
        event: dict[str, Any] = {
            "kind": kind,
            "context_id": result.get("contextId"),
            "state": None,
            "text": None,
            "data": [],
        }

        if kind == "artifact-update":
            artifact = result.get("artifact", {})
            parts = artifact.get("parts", [])
            event["text"] = _extract_text_from_parts(parts)
            event["data"] = _extract_data_from_parts(parts)
        elif kind == "status-update":
            status = result.get("status", {})
            event["state"] = status.get("state")
            message = status.get("message", {})
            event["text"] = _extract_text_from_parts(message.get("parts", []))
        return event

    if isinstance(chunk, dict) and "delta" in chunk and isinstance(chunk["delta"], dict):
        return {"kind": "artifact-update", "context_id": None, "state": None, "text": chunk["delta"].get("text"), "data": []}
    if isinstance(chunk, dict) and "message" in chunk and isinstance(chunk["message"], dict):
        return {"kind": "artifact-update", "context_id": None, "state": None, "text": chunk["message"].get("text"), "data": []}
    if isinstance(chunk, dict) and "content" in chunk:
        return {"kind": "artifact-update", "context_id": None, "state": None, "text": chunk.get("content"), "data": []}
    if isinstance(chunk, dict) and "data" in chunk:
        return {"kind": "artifact-update", "context_id": None, "state": None, "text": None, "data": [chunk.get("data")]}

    return {"kind": "unknown", "context_id": None, "state": None, "text": None, "data": []}


def _should_suppress_status_text(text: str) -> bool:
    """Hide noisy successful status messages while preserving error signals."""
    normalized = re.sub(r"[*`]+", "", text).lower()
    if not LOAD_SKILL_STATUS_RE.search(normalized):
        return False
    return not any(marker in normalized for marker in LOAD_SKILL_ERROR_MARKERS)


def _format_status_text_for_display(status_text: str) -> str:
    """Normalize streamed status whitespace without dropping intentional line breaks."""
    text = status_text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _render_status_panel(
    placeholder,
    status_text: str,
    *,
    state: str | None = None,
    done: bool = False,
    streaming: bool = False,
) -> None:
    display_text = _format_status_text_for_display(status_text)
    if not display_text:
        placeholder.empty()
        return

    title = "Status Updates"
    if state:
        title = f"{title} · {state}"
    if done:
        title = f"{title} · complete"

    cursor = "▌" if streaming else ""
    open_attr = " open" if streaming else ""
    placeholder.markdown(
        f"""
<details class="openstudio-status-panel"{open_attr}>
  <summary class="openstudio-status-panel-title">{html.escape(title)}</summary>
  <div class="openstudio-status-body">{html.escape(display_text + cursor)}</div>
</details>
""",
        unsafe_allow_html=True,
    )


def _should_defer_artifact_render(artifact_text: str) -> bool:
    """Avoid rendering incomplete Markdown table rows during streaming."""
    if artifact_text.endswith("\n"):
        return False
    last_line = artifact_text.rsplit("\n", 1)[-1].strip()
    return last_line.startswith("|") or (
        "|" in last_line and last_line.count("|") >= 2
    )


def _artifact_contains_python_fence(artifact_text: str) -> bool:
    """Return whether an artifact includes a fenced Python script."""
    return "```python" in artifact_text.lower()


def _artifact_contains_json_fence(artifact_text: str) -> bool:
    """Return whether an artifact includes a fenced JSON data payload."""
    return "```json" in artifact_text.lower()


def _split_python_fenced_blocks(artifact_text: str) -> list[tuple[str, str]]:
    """Split artifact text into visible text and fenced Python script blocks."""
    segments: list[tuple[str, str]] = []
    position = 0
    lower_text = artifact_text.lower()
    marker = "```python"

    while True:
        start = lower_text.find(marker, position)
        if start == -1:
            break
        if start > position:
            segments.append(("text", artifact_text[position:start]))
        close = artifact_text.find("```", start + len(marker))
        end = len(artifact_text) if close == -1 else close + 3
        segments.append(("python", artifact_text[start:end]))
        position = end

    if position < len(artifact_text):
        segments.append(("text", artifact_text[position:]))
    return segments


def _render_artifact(
    placeholder,
    artifact_text: str,
    *,
    streaming: bool,
    data_artifacts: list[Any] | None = None,
) -> None:
    data_artifacts = data_artifacts or []
    if not artifact_text and not data_artifacts:
        placeholder.empty()
        return
    if artifact_text and streaming and _should_defer_artifact_render(artifact_text):
        return
    cursor = "▌" if streaming else ""
    with placeholder.container():
        st.markdown(
            '<div class="openstudio-artifact-title">Artifact Update</div>',
            unsafe_allow_html=True,
        )
        if _artifact_contains_python_fence(artifact_text):
            for segment_type, segment_text in _split_python_fenced_blocks(
                artifact_text + cursor
            ):
                if not segment_text:
                    continue
                if segment_type == "python":
                    with st.expander("Generated Python Script", expanded=streaming):
                        st.markdown(segment_text)
                else:
                    st.markdown(segment_text)
        elif _artifact_contains_json_fence(artifact_text):
            with st.expander("Data Artifact", expanded=streaming):
                st.markdown(artifact_text + cursor)
        elif artifact_text:
            st.markdown(artifact_text + cursor)
        for index, data_artifact in enumerate(data_artifacts, start=1):
            label = "Data Artifact" if len(data_artifacts) == 1 else f"Data Artifact {index}"
            with st.expander(label, expanded=streaming):
                st.json(data_artifact)


def main() -> None:
    st.set_page_config(page_title="OpenStudio MCP Demo", page_icon="🏗️", layout="centered")
    st.markdown(STATUS_PANEL_CSS, unsafe_allow_html=True)
    st.title("🏗️ OpenStudio MCP Sizing Demo")

    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            status_text = msg.get("status_text")
            if status_text is None and msg.get("status_updates"):
                status_text = "".join(msg["status_updates"])
            if msg["role"] == "assistant" and status_text:
                status_placeholder = st.empty()
                _render_status_panel(
                    status_placeholder,
                    status_text,
                    state=msg.get("status_state"),
                    done=True,
                )
                if msg.get("content") or msg.get("data_artifacts"):
                    artifact_placeholder = st.empty()
                    _render_artifact(
                        artifact_placeholder,
                        msg.get("content", ""),
                        streaming=False,
                        data_artifacts=msg.get("data_artifacts", []),
                    )
            else:
                st.markdown(msg["content"])

    if prompt := st.chat_input("Ask for an HVAC sizing workflow..."):
        st.session_state["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            status_placeholder = st.empty()
            artifact_placeholder = st.empty()
            status_text = ""
            response_text = ""
            data_artifacts: list[Any] = []
            status_state: str | None = None

            async def process_stream():
                nonlocal response_text, status_text, status_state, data_artifacts
                async for chunk in send_message_async(prompt, st.session_state.get("context_id")):
                    print(chunk)
                    event = _parse_stream_chunk(chunk)
                    context_id = event.get("context_id")
                    if context_id:
                        st.session_state["context_id"] = context_id

                    text_part = event.get("text")
                    event_data = event.get("data") or []
                    if text_part and _should_suppress_status_text(str(text_part)):
                        continue

                    if event.get("kind") == "status-update":
                        if not text_part:
                            continue
                        status_text += str(text_part)
                        status_state = event.get("state")
                        _render_status_panel(
                            status_placeholder,
                            status_text,
                            state=status_state,
                            streaming=True,
                        )
                        continue

                    if event.get("kind") == "artifact-update":
                        if text_part:
                            response_text += str(text_part)
                        if event_data:
                            data_artifacts.extend(event_data)
                        _render_artifact(
                            artifact_placeholder,
                            response_text,
                            streaming=True,
                            data_artifacts=data_artifacts,
                        )

            asyncio.run(process_stream())
            _render_status_panel(
                status_placeholder,
                status_text,
                state=status_state,
                done=bool(status_text),
            )
            _render_artifact(
                artifact_placeholder,
                response_text,
                streaming=False,
                data_artifacts=data_artifacts,
            )

        st.session_state["messages"].append(
            {
                "role": "assistant",
                "content": response_text,
                "data_artifacts": data_artifacts,
                "status_text": status_text,
                "status_state": status_state,
            }
        )


if __name__ == "__main__":
    main()
