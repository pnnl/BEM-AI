"""
AI Message Accumulator for handling streaming chunks from LangChain.

This module provides a class to accumulate AI message chunks, properly routing
content between normal assistant text and artifact outputs based on special markers.
"""

from typing import Any
from langchain_core.messages import AIMessage, AIMessageChunk

ARTIFACT_START = "<<<ARTIFACT_OUTPUT>>>"
ARTIFACT_END = "<<<END_ARTIFACT_OUTPUT>>>"


class AIMessageAccumulator:
    """
    Accumulates AI message chunks and separates assistant text from artifact content.

    Artifacts are enclosed in special markers:
    - Start: <<<ARTIFACT_OUTPUT>>>
    - End: <<<END_ARTIFACT_OUTPUT>>>

    The accumulator handles edge cases like:
    - Markers split across multiple chunks
    - Multiple artifacts in the same message
    - Nested markers (treated as text, not as actual nesting)
    """

    def __init__(self):
        # Text buffers
        self._thread_id: str | None = None
        self._assistant_parts: list[str] = []
        self._artifact_parts: list[str] = []

        # Metadata
        self._additional_kwargs: dict[str, Any] = {}
        self._response_metadata: dict[str, Any] = {}
        self._tool_calls: list[dict] = []

        # State tracking
        self._in_artifact = False
        self._carry = ""  # Handles marker split across chunks

    def add_chunk(self, chunk: AIMessageChunk) -> str:
        """Add a chunk and return the assistant-visible text added by it."""
        assistant_delta_parts: list[str] = []

        def append_assistant(text: str) -> None:
            self._assistant_parts.append(text)
            assistant_delta_parts.append(text)

        # ---- Accumulate metadata ----
        if chunk.additional_kwargs:
            self._merge_dict(self._additional_kwargs, chunk.additional_kwargs)

        if chunk.response_metadata:
            self._response_metadata.update(chunk.response_metadata)

        if getattr(chunk, "tool_calls", None):
            self._tool_calls.extend(chunk.tool_calls)

        # ---- Route content ----
        content_text = self._content_to_text(getattr(chunk, "content", None))
        if not content_text:
            return ""

        text = self._carry + content_text
        self._carry = ""

        while text:
            target_marker = ARTIFACT_START if not self._in_artifact else ARTIFACT_END
            marker_idx = text.find(target_marker)

            if marker_idx != -1:
                # Found complete marker
                if not self._in_artifact:
                    append_assistant(text[:marker_idx])
                    text = text[marker_idx + len(ARTIFACT_START):]
                    self._in_artifact = True
                else:
                    self._artifact_parts.append(text[:marker_idx])
                    text = text[marker_idx + len(ARTIFACT_END):]
                    self._in_artifact = False
            else:
                # No complete marker - check for partial
                max_partial = min(len(text), len(target_marker) - 1)
                partial_found = False

                # Check from longest possible partial down to 1 char
                for length in range(max_partial, 0, -1):
                    if target_marker.startswith(text[-length:]):
                        # Found a partial marker at the end
                        if not self._in_artifact:
                            append_assistant(text[:-length])
                        else:
                            self._artifact_parts.append(text[:-length])
                        self._carry = text[-length:]
                        partial_found = True
                        break

                if not partial_found:
                    # No partial marker, add everything
                    if not self._in_artifact:
                        append_assistant(text)
                    else:
                        self._artifact_parts.append(text)
                break

        return "".join(assistant_delta_parts)

    def finalize(self) -> AIMessage:
        """
        Finalize the accumulated chunks into a complete AIMessage, and reset the state

        Returns:
            AIMessage with all accumulated content and metadata
        """
        # Handle any remaining carry (shouldn't happen in normal use)
        if self._carry:
            if self._in_artifact:
                self._artifact_parts.append(self._carry)
            else:
                self._assistant_parts.append(self._carry)
            self._carry = ""

        assistant_part = "".join(self._assistant_parts).strip() or ""
        artifact_part = "".join(self._artifact_parts).strip() or ""

        if assistant_part and artifact_part:
            assistant_part = assistant_part + " "

        combine_parts = assistant_part + artifact_part

        # Build the final message
        message = AIMessage(
            content=combine_parts,
            additional_kwargs=self._additional_kwargs if self._additional_kwargs else {},
            response_metadata=self._response_metadata if self._response_metadata else {},
            tool_calls=self._tool_calls if self._tool_calls else [],
        )

        # Reset state for potential reuse
        self._assistant_parts.clear()
        self._artifact_parts.clear()
        self._additional_kwargs.clear()
        self._response_metadata.clear()
        self._tool_calls.clear()
        self._in_artifact = False
        self._carry = ""
        return message

    def get_last_assistant_text(self) -> str | None:
        """
                Get the last assistant text.

                Returns:
                    The assistant text (stripped of whitespace), or None if no assistant
                """
        if not self._assistant_parts:
            return None
        return self._assistant_parts[-1]

    def get_assistant_text(self) -> str | None:
        """
        Get the accumulated assistant content.

        Returns:
            The assistant text (stripped of whitespace), or None if no assistant
        """
        if not self._assistant_parts:
            return None
        return "".join(self._assistant_parts).strip()

    def get_artifact_text(self) -> str | None:
        """
        Get the accumulated artifact content.

        Returns:
            The artifact text (stripped of whitespace), or None if no artifact
        """
        if not self._artifact_parts:
            return None
        artifact_text = "".join(self._artifact_parts).strip()
        return artifact_text if artifact_text else None

    def _merge_dict(self, target: dict, source: dict) -> None:
        """
        Merge dictionaries recursively, with last-write-wins for scalars.

        Args:
            target: Dictionary to merge into
            source: Dictionary to merge from
        """
        for key, value in source.items():
            if (
                    key in target
                    and isinstance(target[key], dict)
                    and isinstance(value, dict)
            ):
                self._merge_dict(target[key], value)
            else:
                target[key] = value

    def _get_partial_marker_length(self, text: str, marker: str) -> int:
        """
        Check if text ends with a partial marker.

        This handles the edge case where a marker is split across chunks.
        For example, if the marker is "<<<ARTIFACT>>>" and the text ends with
        "<<<AR", we return 5 so those characters can be carried over.

        Args:
            text: The text to check
            marker: The marker to look for partial matches of

        Returns:
            Length of the partial marker at the end of text, or 0 if none
        """
        for i in range(1, len(marker)):
            if text.endswith(marker[:i]):
                return i
        return 0

    def _content_to_text(self, content: Any) -> str:
        """Convert LangChain message content into a plain string."""
        if content is None:
            return ""

        # Standard case: already a string
        if isinstance(content, str):
            return content

        # Gemini / some providers: list of content parts (dicts)
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    # Common pattern: {'type': 'text', 'text': '...'}
                    if item.get("type") == "text" and "text" in item:
                        parts.append(item["text"])
                    # Some implementations may use other keys
                    elif "text" in item and isinstance(item["text"], str):
                        parts.append(item["text"])
                    else:
                        # ignore non-text blocks (or log if you prefer)
                        pass
            return "".join(parts)

        # Anything else: best-effort string conversion
        return str(content)
