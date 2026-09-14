
import asyncio
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StreamText:
    """Text extracted from one serialized A2A stream response."""

    text: str = ""
    is_final: bool = False
    append: bool = False
    state: str | None = None

    @property
    def replaces_text(self) -> bool:
        """Whether this event supplies a complete terminal response."""
        return self.is_final and not self.append


def _text_from_parts(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""

    text: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("kind") == "text" and part.get("text"):
            text.append(str(part["text"]))
    return "\n".join(text)


def _coerce_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, indent=2, sort_keys=True)


def extract_stream_text(chunk: Any) -> StreamText:
    """Extract visible text from legacy and protobuf-backed A2A stream chunks.

    A completed A2A task carries its canonical output in ``artifacts`` rather
    than in ``status.message``. UIs replace accumulated token updates only for
    a non-appended terminal artifact; appended artifact chunks remain suffixes.
    """
    if not isinstance(chunk, dict):
        return StreamText()

    result = chunk.get("result")
    if isinstance(result, dict):
        kind = result.get("kind")
        status = result.get("status") if isinstance(result.get("status"), dict) else {}
        state = status.get("state")
        status_text = _text_from_parts(
            status.get("message", {}).get("parts", [])
            if isinstance(status.get("message"), dict)
            else []
        )

        if kind == "task":
            artifact_text = "\n".join(
                text
                for artifact in result.get("artifacts", [])
                if isinstance(artifact, dict)
                if (text := _text_from_parts(artifact.get("parts", [])))
            )
            return StreamText(
                text=artifact_text or status_text,
                is_final=state == "completed",
                state=state,
            )
        if kind == "artifact-update":
            artifact = result.get("artifact", {})
            return StreamText(
                text=_text_from_parts(artifact.get("parts", []))
                if isinstance(artifact, dict)
                else "",
                is_final=bool(result.get("lastChunk")),
                append=bool(result.get("append")),
                state=state,
            )
        if kind == "status-update":
            return StreamText(text=status_text, state=state)
        if kind == "message":
            return StreamText(text=_text_from_parts(result.get("parts", [])))

    if isinstance(chunk.get("delta"), dict) and "text" in chunk["delta"]:
        return StreamText(text=_coerce_text(chunk["delta"]["text"]))
    if isinstance(chunk.get("message"), dict) and "text" in chunk["message"]:
        return StreamText(text=_coerce_text(chunk["message"]["text"]))
    if "content" in chunk:
        return StreamText(text=_coerce_text(chunk["content"]))
    if "data" in chunk:
        return StreamText(text=_coerce_text(chunk["data"]))
    return StreamText()

# ---------------------------------------------------------------------
# Natural slow-streaming effect
# ---------------------------------------------------------------------
async def natural_delay(text_fragment: str):
    """Add a natural delay based on fragment length."""
    # You can tune these values
    base_delay = 0.02  # 20 ms
    per_char_delay = 0.002  # +2 ms per character

    delay = base_delay + len(text_fragment) * per_char_delay
    await asyncio.sleep(delay)
