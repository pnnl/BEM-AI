import asyncio
import html
import json
import os
import re
from collections import deque
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from automa_ai.client.simple_client import SimpleClient

base_dir = Path(__file__).resolve().parent
env_path = base_dir / ".env"
load_dotenv(dotenv_path=env_path)

A2A_SERVER_URL = os.getenv("CHATBOT_SERVER_URL", "http://localhost:9999")
TELEMETRY_LOG_PATH = base_dir / "logs" / "telemetry.jsonl"
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
.openstudio-telemetry-panel {
    height: calc(100vh - 7rem);
    overflow-y: auto;
    padding-right: 0.4rem;
}
.openstudio-telemetry-title {
    color: #111827;
    font-size: 1.05rem;
    font-weight: 700;
    margin: 0.25rem 0 0.15rem;
}
.openstudio-telemetry-caption {
    color: #6b7280;
    font-size: 0.76rem;
    margin-bottom: 0.6rem;
    overflow-wrap: anywhere;
}
.openstudio-telemetry-empty {
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    color: #6b7280;
    font-size: 0.84rem;
    padding: 0.7rem;
}
.openstudio-trace {
    border: 1px solid #d1d5db;
    border-radius: 6px;
    margin: 0 0 0.55rem;
    overflow: hidden;
}
.openstudio-trace > summary {
    background: #f3f4f6;
    color: #111827;
    cursor: pointer;
    font-size: 0.82rem;
    font-weight: 650;
    padding: 0.45rem 0.55rem;
}
.openstudio-span {
    border-left: 2px solid #9ca3af;
    margin: 0.45rem 0 0.45rem 0.55rem;
    padding-left: 0.45rem;
}
.openstudio-span > summary {
    color: #1f2937;
    cursor: pointer;
    font-size: 0.8rem;
    font-weight: 600;
    overflow-wrap: anywhere;
}
.openstudio-span-error {
    border-left-color: #dc2626;
}
.openstudio-event {
    border-left: 2px solid #d1d5db;
    color: #374151;
    font-size: 0.75rem;
    margin: 0.35rem 0 0.35rem 0.4rem;
    padding-left: 0.45rem;
}
.openstudio-telemetry-attrs {
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    margin: 0.3rem 0;
    padding: 0.35rem 0.45rem;
}
.openstudio-telemetry-row {
    border-top: 1px solid #eef0f3;
    display: grid;
    gap: 0.35rem;
    grid-template-columns: minmax(5.5rem, 36%) 1fr;
    padding: 0.18rem 0;
}
.openstudio-telemetry-row:first-child {
    border-top: 0;
}
.openstudio-telemetry-key {
    color: #6b7280;
    font-size: 0.68rem;
    font-weight: 650;
    overflow-wrap: anywhere;
}
.openstudio-telemetry-value {
    color: #374151;
    font-size: 0.7rem;
    line-height: 1.35;
    overflow-wrap: anywhere;
}
.openstudio-telemetry-message {
    background: #ffffff;
    border-left: 2px solid #9ca3af;
    margin: 0.3rem 0;
    padding: 0.3rem 0.45rem;
}
.openstudio-telemetry-meta {
    color: #6b7280;
    font-size: 0.7rem;
    margin: 0.15rem 0;
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


def _read_recent_telemetry_records(
    path: Path,
    *,
    max_records: int = 500,
) -> list[dict[str, Any]]:
    """Read recent JSONL telemetry records from disk without owning the writer."""
    if not path.exists():
        return []

    records: deque[dict[str, Any]] = deque(maxlen=max_records)
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except json.JSONDecodeError:
                # The JSONL recorder writes full lines, but tolerate a partial
                # line if the UI reads while another process is writing.
                continue
            if isinstance(item, dict):
                records.append(item)
    return list(records)


def _select_telemetry_records_for_context(
    records: list[dict[str, Any]],
    context_id: str | None,
) -> list[dict[str, Any]]:
    """Return all records for the active session's traces when possible."""
    if not context_id:
        return records

    trace_ids = {
        record.get("trace_id")
        for record in records
        if record.get("trace_id")
        and isinstance(record.get("attributes"), dict)
        and record["attributes"].get("session.id") == context_id
    }
    if not trace_ids:
        return records
    return [record for record in records if record.get("trace_id") in trace_ids]


def _group_telemetry_by_trace(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build trace/span/event trees from JSONL span_start/event/span_end records."""
    traces: dict[str, dict[str, Any]] = {}
    trace_order: list[str] = []

    for index, record in enumerate(records):
        trace_id = str(record.get("trace_id") or "untraced")
        if trace_id not in traces:
            traces[trace_id] = {
                "trace_id": trace_id,
                "spans": {},
                "roots": [],
                "events": [],
                "last_index": index,
            }
            trace_order.append(trace_id)
        trace = traces[trace_id]
        trace["last_index"] = index

        record_type = record.get("type")
        span_id = record.get("span_id")
        if record_type in {"span_start", "span_end"}:
            node = _ensure_telemetry_span_node(trace, record)
            if record_type == "span_start":
                node["start"] = record
                node["name"] = record.get("name") or node["name"]
                node["kind"] = record.get("kind") or node["kind"]
                node["timestamp"] = record.get("timestamp") or node["timestamp"]
                node["parent_span_id"] = record.get("parent_span_id")
            else:
                node["end"] = record
                node["status"] = record.get("status")
                node["duration_ms"] = record.get("duration_ms")
        elif record_type == "event":
            if span_id:
                node = _ensure_telemetry_span_node(trace, record)
                node["events"].append(record)
            else:
                trace["events"].append(record)

    for trace in traces.values():
        _link_telemetry_span_tree(trace)

    return [traces[trace_id] for trace_id in trace_order]


def _ensure_telemetry_span_node(
    trace: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    """Create a span node once, then merge later start/end/event records into it."""
    span_id = str(record.get("span_id") or "missing-span")
    spans = trace["spans"]
    if span_id not in spans:
        spans[span_id] = {
            "span_id": span_id,
            "parent_span_id": record.get("parent_span_id"),
            "name": record.get("name") or "unknown span",
            "kind": record.get("kind"),
            "timestamp": record.get("timestamp"),
            "status": None,
            "duration_ms": None,
            "start": None,
            "end": None,
            "events": [],
            "children": [],
        }
    return spans[span_id]


def _link_telemetry_span_tree(trace: dict[str, Any]) -> None:
    """Link spans by parent id after all records are read, preserving file order."""
    for node in trace["spans"].values():
        node["children"] = []
    roots = []
    for node in trace["spans"].values():
        parent_id = node.get("parent_span_id")
        parent = trace["spans"].get(str(parent_id)) if parent_id else None
        if parent is not None and parent is not node:
            parent["children"].append(node)
        else:
            roots.append(node)
    trace["roots"] = roots


TELEMETRY_PRIMARY_KEYS = (
    "message.role",
    "message.content",
    "artifact.content",
    "tool.name",
    "tool.arguments",
    "tool.result",
    "stream.close.reason",
    "exception.type",
    "exception.message",
    "session.id",
    "task.id",
    "user.id",
    "agent.name",
)
TELEMETRY_LOW_SIGNAL_KEYS = {
    "agent.description",
    "agent.runtime",
    "deployment.environment",
    "service.name",
}


def _stringify_telemetry_value(value: Any, *, max_chars: int = 420) -> str:
    """Summarize telemetry values without falling back to raw JSON blocks."""
    if value is None:
        return "none"
    if isinstance(value, dict):
        if set(value) >= {"length", "sha256"}:
            digest = str(value.get("sha256") or "")
            length = value.get("length")
            return f"metadata only ({length} chars, sha256 {digest[:12]}...)"
        if "content" in value and len(value) == 1:
            return _truncate_telemetry_text(str(value["content"]), max_chars=max_chars)
        pairs = []
        for key in sorted(value):
            summary = _stringify_telemetry_value(value[key], max_chars=120)
            pairs.append(f"{key}: {summary}")
        return _truncate_telemetry_text("; ".join(pairs), max_chars=max_chars)
    if isinstance(value, list):
        if not value:
            return "none"
        sample = ", ".join(
            _stringify_telemetry_value(item, max_chars=80) for item in value[:3]
        )
        suffix = "" if len(value) <= 3 else f", +{len(value) - 3} more"
        return _truncate_telemetry_text(
            f"{len(value)} item(s): {sample}{suffix}", max_chars=max_chars
        )

    return _truncate_telemetry_text(str(value), max_chars=max_chars)


def _truncate_telemetry_text(text: str, *, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3]}..."


def _ordered_telemetry_attributes(attrs: dict[str, Any]) -> list[tuple[str, Any]]:
    """Put human-important fields first and hide noisy defaults unless needed."""
    ordered_keys = [key for key in TELEMETRY_PRIMARY_KEYS if key in attrs]
    remaining_keys = sorted(
        key
        for key in attrs
        if key not in ordered_keys and key not in TELEMETRY_LOW_SIGNAL_KEYS
    )
    if not ordered_keys and not remaining_keys:
        remaining_keys = sorted(attrs)
    return [(key, attrs[key]) for key in ordered_keys + remaining_keys]


def _render_telemetry_attributes(attrs: dict[str, Any]) -> str:
    if not attrs:
        return ""

    rows = []
    for key, value in _ordered_telemetry_attributes(attrs):
        rows.append(
            '<div class="openstudio-telemetry-row">'
            f'<div class="openstudio-telemetry-key">{html.escape(key)}</div>'
            f'<div class="openstudio-telemetry-value">{html.escape(_stringify_telemetry_value(value))}</div>'
            "</div>"
        )
    return '<div class="openstudio-telemetry-attrs">' + "\n".join(rows) + "</div>"


def _render_telemetry_message_summary(attrs: dict[str, Any]) -> str:
    """Render message events as a readable summary before the full attributes."""
    if "message.role" not in attrs and "message.content" not in attrs:
        return ""

    role = html.escape(str(attrs.get("message.role") or "message"))
    content = html.escape(_stringify_telemetry_value(attrs.get("message.content")))
    return (
        '<div class="openstudio-telemetry-message">'
        f'<div class="openstudio-telemetry-key">Message · {role}</div>'
        f'<div class="openstudio-telemetry-value">{content}</div>'
        "</div>"
    )


def _format_duration_ms(value: Any) -> str:
    if value is None:
        return "open"
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return str(value)
    if duration >= 1000:
        return f"{duration / 1000:.1f}s"
    return f"{duration:.0f}ms"


def _render_telemetry_html(traces: list[dict[str, Any]]) -> str:
    trace_html = []
    visible_traces = traces[-8:]
    latest_index = len(visible_traces) - 1
    for index, trace in enumerate(visible_traces):
        trace_id = trace["trace_id"]
        roots = trace.get("roots", [])
        events = trace.get("events", [])
        trace_open = index == latest_index
        open_attr = " open" if trace_open else ""
        trace_html.append(
            f'<details class="openstudio-trace"{open_attr}>'
            f"<summary>Trace {html.escape(trace_id[:12])} · "
            f"{len(roots)} root span(s)</summary>"
        )
        for node in roots:
            trace_html.append(
                _render_telemetry_span_node(
                    node,
                    depth=0,
                    expand_root=trace_open,
                )
            )
        for event in events:
            trace_html.append(_render_telemetry_event(event))
        trace_html.append("</details>")
    return "\n".join(trace_html)


def _render_telemetry_span_node(
    node: dict[str, Any],
    *,
    depth: int,
    expand_root: bool,
) -> str:
    status = node.get("status") or "open"
    status_label = "error" if status == "error" else status
    css_class = (
        "openstudio-span openstudio-span-error"
        if status == "error"
        else "openstudio-span"
    )
    expanded = " open" if depth == 0 and expand_root else ""
    name = html.escape(str(node.get("name") or "unknown span"))
    kind = html.escape(str(node.get("kind") or ""))
    span_id = html.escape(str(node.get("span_id") or "")[:8])
    duration = html.escape(_format_duration_ms(node.get("duration_ms")))

    parts = [
        f'<details class="{css_class}"{expanded}>',
        (
            f"<summary>{name} · {html.escape(status_label)} · {duration} "
            f'<span class="openstudio-telemetry-meta">#{span_id} {kind}</span></summary>'
        ),
    ]

    start = node.get("start") or {}
    end = node.get("end") or {}
    attrs = start.get("attributes") or {}
    end_attrs = end.get("attributes") or {}
    if attrs:
        parts.append('<div class="openstudio-telemetry-meta">Start</div>')
        parts.append(_render_telemetry_attributes(attrs))
    if end_attrs:
        parts.append('<div class="openstudio-telemetry-meta">End</div>')
        parts.append(_render_telemetry_attributes(end_attrs))

    for event in node.get("events", []):
        parts.append(_render_telemetry_event(event))
    for child in node.get("children", []):
        parts.append(
            _render_telemetry_span_node(
                child,
                depth=depth + 1,
                expand_root=False,
            )
        )

    parts.append("</details>")
    return "\n".join(parts)


def _render_telemetry_event(event: dict[str, Any]) -> str:
    name = html.escape(str(event.get("name") or "event"))
    timestamp = html.escape(str(event.get("timestamp") or ""))
    attrs = event.get("attributes") or {}
    return (
        '<div class="openstudio-event">'
        f"<strong>{name}</strong>"
        f'<div class="openstudio-telemetry-meta">{timestamp}</div>'
        f"{_render_telemetry_message_summary(attrs)}"
        f"{_render_telemetry_attributes(attrs)}"
        "</div>"
    )


def _render_telemetry_panel(
    placeholder,
    *,
    context_id: str | None,
    log_path: Path = TELEMETRY_LOG_PATH,
) -> None:
    records = _read_recent_telemetry_records(log_path)
    selected_records = _select_telemetry_records_for_context(records, context_id)
    traces = _group_telemetry_by_trace(selected_records)

    body = ""
    if not records:
        body = (
            '<div class="openstudio-telemetry-empty">'
            "No telemetry records yet. Start a task to populate the JSONL log."
            "</div>"
        )
    elif not traces:
        body = (
            '<div class="openstudio-telemetry-empty">'
            "Telemetry records are present, but no trace tree could be built."
            "</div>"
        )
    else:
        body = _render_telemetry_html(traces)

    placeholder.markdown(
        (
            '<div class="openstudio-telemetry-panel">'
            '<div class="openstudio-telemetry-title">Telemetry</div>'
            '<div class="openstudio-telemetry-caption">'
            f"{html.escape(str(log_path))}<br>"
            f"{len(selected_records)} recent record(s)"
            "</div>"
            f"{body}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title="OpenStudio AI", page_icon="🏗️", layout="wide")
    st.markdown(STATUS_PANEL_CSS, unsafe_allow_html=True)

    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    with st.sidebar:
        telemetry_placeholder = st.empty()
        _render_telemetry_panel(
            telemetry_placeholder,
            context_id=st.session_state.get("context_id"),
        )

    st.title("🏗️ OpenStudio AI")

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

    prompt = st.chat_input("Ask for an HVAC sizing workflow...")
    if prompt:
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
                async for chunk in send_message_async(
                    prompt, st.session_state.get("context_id")
                ):
                    print(chunk)
                    event = _parse_stream_chunk(chunk)
                    context_id = event.get("context_id")
                    if context_id:
                        st.session_state["context_id"] = context_id
                        _render_telemetry_panel(
                            telemetry_placeholder,
                            context_id=context_id,
                        )

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
                        _render_telemetry_panel(
                            telemetry_placeholder,
                            context_id=st.session_state.get("context_id"),
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
                        _render_telemetry_panel(
                            telemetry_placeholder,
                            context_id=st.session_state.get("context_id"),
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
            _render_telemetry_panel(
                telemetry_placeholder,
                context_id=st.session_state.get("context_id"),
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
