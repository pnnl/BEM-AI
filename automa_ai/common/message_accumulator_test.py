"""
Unit tests for AIMessageAccumulator class.

These tests cover:
- Basic functionality (text routing, metadata accumulation)
- Edge cases (split markers, multiple artifacts, empty chunks)
- Metadata merging
- Tool calls
"""

import pytest
from langchain_core.messages import AIMessageChunk
from automa_ai.common.message_accumulator import (
    AIMessageAccumulator,
    ARTIFACT_START,
    ARTIFACT_END,
)


class TestBasicFunctionality:
    """Test basic accumulation and routing."""

    def test_simple_text_no_artifact(self):
        """Test accumulating simple text without any artifact."""
        acc = AIMessageAccumulator()

        assert acc.add_chunk(AIMessageChunk(content="Hello ")) == "Hello "
        assert acc.add_chunk(AIMessageChunk(content="world!")) == "world!"

        assert acc.get_assistant_text() == "Hello world!"
        assert acc.get_artifact_text() is None

        msg = acc.finalize()
        assert msg.content == "Hello world!"

    def test_simple_artifact(self):
        """Test accumulating a simple artifact."""
        acc = AIMessageAccumulator()

        assert (
            acc.add_chunk(
                AIMessageChunk(content=f"Here is your file: {ARTIFACT_START}")
            )
            == "Here is your file: "
        )
        assert (
            acc.add_chunk(AIMessageChunk(content="def hello():\n    print('Hello')"))
            == ""
        )
        assert acc.add_chunk(AIMessageChunk(content=f"{ARTIFACT_END}")) == ""

        assert acc.get_assistant_text() == "Here is your file:"
        assert acc.get_artifact_text() == "def hello():\n    print('Hello')"

        msg = acc.finalize()
        assert msg.content == "Here is your file: def hello():\n    print('Hello')"

    def test_text_before_and_after_artifact(self):
        """Test text both before and after an artifact."""
        acc = AIMessageAccumulator()

        assert (
            acc.add_chunk(
                AIMessageChunk(
                    content=f"Before {ARTIFACT_START}artifact{ARTIFACT_END} after"
                )
            )
            == "Before  after"
        )

        assert acc.get_assistant_text() == "Before  after"
        assert acc.get_artifact_text() == "artifact"

        msg = acc.finalize()
        assert msg.content == "Before  after artifact"

    def test_artifact_marker_content_is_not_returned_as_assistant_delta(self):
        """Artifact content split across chunks is not returned for status streaming."""
        acc = AIMessageAccumulator()

        assert (
            acc.add_chunk(AIMessageChunk(content=f"Summary {ARTIFACT_START}"))
            == "Summary "
        )
        assert acc.add_chunk(AIMessageChunk(content='{"foo": "bar"}')) == ""
        assert acc.add_chunk(AIMessageChunk(content=ARTIFACT_END)) == ""

        assert acc.get_assistant_text() == "Summary"
        assert acc.get_artifact_text() == '{"foo": "bar"}'

    def test_provider_list_text_content_returns_assistant_delta(self):
        """Provider list content blocks are converted before artifact routing."""
        acc = AIMessageAccumulator()

        delta = acc.add_chunk(
            AIMessageChunk(
                content=[
                    {"type": "text", "text": "hello"},
                    {"type": "text", "text": " world"},
                ],
                response_metadata={"model_provider": "bedrock_converse"},
            )
        )

        assert delta == "hello world"
        assert acc.get_assistant_text() == "hello world"

    def test_multiple_artifacts(self):
        """Test multiple artifacts (they get concatenated)."""
        acc = AIMessageAccumulator()

        acc.add_chunk(
            AIMessageChunk(
                content=f"{ARTIFACT_START}first{ARTIFACT_END} middle {ARTIFACT_START}second{ARTIFACT_END}"
            )
        )

        assert acc.get_assistant_text() == "middle"
        # Both artifacts are concatenated
        assert acc.get_artifact_text() == "firstsecond"
        msg = acc.finalize()
        assert msg.content == "middle firstsecond"

    def test_empty_artifact(self):
        """Test an empty artifact."""
        acc = AIMessageAccumulator()

        acc.add_chunk(
            AIMessageChunk(content=f"Text {ARTIFACT_START}{ARTIFACT_END} more")
        )

        assert acc.get_assistant_text() == "Text  more"
        # Empty string strips to None
        assert acc.get_artifact_text() is None

        msg = acc.finalize()
        assert msg.content == "Text  more"

    def test_whitespace_only_artifact(self):
        """Test an artifact with only whitespace."""
        acc = AIMessageAccumulator()

        acc.add_chunk(AIMessageChunk(content=f"{ARTIFACT_START}   \n  {ARTIFACT_END}"))

        assert acc.get_assistant_text() == ""
        # Whitespace is stripped
        assert acc.get_artifact_text() is None

        msg = acc.finalize()
        assert msg.content == ""


class TestSplitMarkers:
    """Test handling of markers split across chunks."""

    def test_start_marker_split_simple(self):
        """Test artifact start marker split across two chunks."""
        acc = AIMessageAccumulator()

        # Split the marker in the middle
        marker_split = len(ARTIFACT_START) // 2
        acc.add_chunk(AIMessageChunk(content=f"Text {ARTIFACT_START[:marker_split]}"))
        acc.add_chunk(
            AIMessageChunk(
                content=f"{ARTIFACT_START[marker_split:]}content{ARTIFACT_END}"
            )
        )

        assert acc.get_assistant_text() == "Text"
        assert acc.get_artifact_text() == "content"

        msg = acc.finalize()
        assert msg.content == "Text content"

    def test_end_marker_split_simple(self):
        """Test artifact end marker split across two chunks."""
        acc = AIMessageAccumulator()

        marker_split = len(ARTIFACT_END) // 2
        acc.add_chunk(
            AIMessageChunk(
                content=f"{ARTIFACT_START}content{ARTIFACT_END[:marker_split]}"
            )
        )
        acc.add_chunk(AIMessageChunk(content=f"{ARTIFACT_END[marker_split:]} after"))

        assert acc.get_assistant_text() == "after"
        assert acc.get_artifact_text() == "content"

        msg = acc.finalize()
        assert msg.content == "after content"

    def test_start_marker_split_one_char(self):
        """Test start marker split with only one character in first chunk."""
        acc = AIMessageAccumulator()

        acc.add_chunk(AIMessageChunk(content="Text <"))
        acc.add_chunk(
            AIMessageChunk(
                content="<<ARTIFACT_OUTPUT>>>content<<<END_ARTIFACT_OUTPUT>>>"
            )
        )

        assert acc.get_assistant_text() == "Text"
        assert acc.get_artifact_text() == "content"

        msg = acc.finalize()
        assert msg.content == "Text content"

    def test_end_marker_split_one_char(self):
        """Test end marker split with only one character in first chunk."""
        acc = AIMessageAccumulator()

        acc.add_chunk(AIMessageChunk(content="<<<ARTIFACT_OUTPUT>>>content<"))
        acc.add_chunk(AIMessageChunk(content="<<END_ARTIFACT_OUTPUT>>> after"))

        assert acc.get_assistant_text() == "after"
        assert acc.get_artifact_text() == "content"

        msg = acc.finalize()
        assert msg.content == "after content"

    def test_false_partial_marker(self):
        """Test that similar but different text doesn't trigger partial marker logic."""
        acc = AIMessageAccumulator()

        # "<<<" looks like start of marker but isn't actually the marker
        acc.add_chunk(AIMessageChunk(content="Use <<< for comparison"))
        acc.add_chunk(AIMessageChunk(content=" operators"))

        assert acc.get_assistant_text() == "Use <<< for comparison operators"
        assert acc.get_artifact_text() is None

        msg = acc.finalize()
        assert msg.content == "Use <<< for comparison operators"

    def test_marker_split_three_ways(self):
        """Test marker split across three chunks."""
        acc = AIMessageAccumulator()

        # Split into three parts
        acc.add_chunk(AIMessageChunk(content="<<<"))
        acc.add_chunk(AIMessageChunk(content="ARTIFACT_"))
        acc.add_chunk(
            AIMessageChunk(content="OUTPUT>>>content<<<END_ARTIFACT_OUTPUT>>>")
        )

        assert acc.get_assistant_text() == ""
        assert acc.get_artifact_text() == "content"

        msg = acc.finalize()
        assert msg.content == "content"


class TestMetadata:
    """Test metadata accumulation."""

    def test_additional_kwargs_simple(self):
        """Test accumulating additional_kwargs."""
        acc = AIMessageAccumulator()

        acc.add_chunk(
            AIMessageChunk(content="test", additional_kwargs={"model": "gpt-4"})
        )
        acc.add_chunk(
            AIMessageChunk(content="", additional_kwargs={"temperature": 0.7})
        )

        msg = acc.finalize()
        assert msg.additional_kwargs == {"model": "gpt-4", "temperature": 0.7}

    def test_additional_kwargs_nested_merge(self):
        """Test merging nested dictionaries in additional_kwargs."""
        acc = AIMessageAccumulator()

        acc.add_chunk(
            AIMessageChunk(
                content="", additional_kwargs={"usage": {"prompt_tokens": 10}}
            )
        )
        acc.add_chunk(
            AIMessageChunk(
                content="", additional_kwargs={"usage": {"completion_tokens": 20}}
            )
        )

        msg = acc.finalize()
        assert msg.additional_kwargs == {
            "usage": {"prompt_tokens": 10, "completion_tokens": 20}
        }

    def test_additional_kwargs_overwrite(self):
        """Test that later values overwrite earlier ones."""
        acc = AIMessageAccumulator()

        acc.add_chunk(
            AIMessageChunk(content="", additional_kwargs={"model": "gpt-3.5"})
        )
        acc.add_chunk(AIMessageChunk(content="", additional_kwargs={"model": "gpt-4"}))

        msg = acc.finalize()
        assert msg.additional_kwargs["model"] == "gpt-4"

    def test_response_metadata(self):
        """Test accumulating response_metadata."""
        acc = AIMessageAccumulator()

        acc.add_chunk(AIMessageChunk(content="", response_metadata={"stop": "end"}))
        acc.add_chunk(
            AIMessageChunk(content="", response_metadata={"finish_reason": "stop"})
        )

        msg = acc.finalize()
        assert msg.response_metadata == {"stop": "end", "finish_reason": "stop"}

    def test_usage_metadata(self):
        """Test accumulating usage_metadata."""
        acc = AIMessageAccumulator()

        acc.add_chunk(
            AIMessageChunk(
                content="",
                usage_metadata={
                    "input_tokens": 5,
                    "output_tokens": 2,
                    "total_tokens": 7,
                },
            )
        )
        acc.add_chunk(
            AIMessageChunk(
                content="",
                usage_metadata={
                    "input_tokens": 0,
                    "output_tokens": 8,
                    "total_tokens": 8,
                },
            )
        )

        msg = acc.finalize()
        assert msg.usage_metadata == {
            "input_tokens": 5,
            "output_tokens": 10,
            "total_tokens": 15,
        }

    def test_tool_calls(self):
        """Test accumulating tool calls."""
        acc = AIMessageAccumulator()

        tool_call_1 = {
            "id": "123",
            "name": "search",
            "args": {"query": "test"},
            "type": "tool_call",
        }
        tool_call_2 = {
            "id": "456",
            "name": "calculator",
            "args": {"expression": "2+2"},
            "type": "tool_call",
        }

        acc.add_chunk(AIMessageChunk(content="", tool_calls=[tool_call_1]))
        acc.add_chunk(AIMessageChunk(content="", tool_calls=[tool_call_2]))

        msg = acc.finalize()
        assert msg.tool_calls == [tool_call_1, tool_call_2]


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_chunks(self):
        """Test handling empty chunks."""
        acc = AIMessageAccumulator()

        acc.add_chunk(AIMessageChunk(content=""))
        acc.add_chunk(AIMessageChunk(content="Hello"))
        acc.add_chunk(AIMessageChunk(content=""))
        acc.add_chunk(AIMessageChunk(content=" world"))
        acc.add_chunk(AIMessageChunk(content=""))

        msg = acc.finalize()
        assert msg.content == "Hello world"

    def test_unclosed_artifact(self):
        """Test handling an artifact that's never closed."""
        acc = AIMessageAccumulator()

        acc.add_chunk(AIMessageChunk(content=f"Text {ARTIFACT_START}artifact content"))

        assert acc.get_assistant_text() == "Text"
        assert acc.get_artifact_text() == "artifact content"

        msg = acc.finalize()
        assert msg.content == "Text artifact content"

    def test_unopened_artifact_end(self):
        """Test handling an end marker without a start marker."""
        acc = AIMessageAccumulator()

        # End marker without start - should be treated as normal text
        acc.add_chunk(AIMessageChunk(content=f"Text {ARTIFACT_END} more"))

        assert acc.get_assistant_text() == f"Text {ARTIFACT_END} more"
        assert acc.get_artifact_text() is None

        msg = acc.finalize()
        assert msg.content == f"Text {ARTIFACT_END} more"

    def test_nested_start_markers(self):
        """Test handling nested start markers (second start is treated as content)."""
        acc = AIMessageAccumulator()

        acc.add_chunk(
            AIMessageChunk(
                content=f"{ARTIFACT_START}content {ARTIFACT_START} more{ARTIFACT_END}"
            )
        )

        assert acc.get_assistant_text() == ""
        # The nested start marker is part of the artifact content
        assert acc.get_artifact_text() == f"content {ARTIFACT_START} more"

        msg = acc.finalize()
        assert msg.content == f"content {ARTIFACT_START} more"

    def test_multiple_consecutive_chunks_same_content(self):
        """Test adding many chunks with the same content."""
        acc = AIMessageAccumulator()

        for _ in range(100):
            acc.add_chunk(AIMessageChunk(content="a"))

        msg = acc.finalize()
        assert msg.content == "a" * 100

    def test_large_artifact(self):
        """Test handling a large artifact."""
        acc = AIMessageAccumulator()

        large_content = "x" * 10000
        acc.add_chunk(
            AIMessageChunk(content=f"{ARTIFACT_START}{large_content}{ARTIFACT_END}")
        )

        assert acc.get_assistant_text() == ""
        assert acc.get_artifact_text() == large_content

        msg = acc.finalize()
        assert msg.content == large_content

    def test_marker_as_part_of_content(self):
        """Test that markers inside artifact are treated as content."""
        acc = AIMessageAccumulator()

        acc.add_chunk(
            AIMessageChunk(
                content=f"{ARTIFACT_START}This contains {ARTIFACT_START} in the middle{ARTIFACT_END}"
            )
        )

        assert (
            acc.get_artifact_text() == f"This contains {ARTIFACT_START} in the middle"
        )
        msg = acc.finalize()
        assert msg.content == f"This contains {ARTIFACT_START} in the middle"


class TestComplexScenarios:
    """Test complex real-world scenarios."""

    def test_streaming_code_with_explanation(self):
        """Test a realistic scenario of streaming code with explanation."""
        acc = AIMessageAccumulator()

        chunks = [
            "Here's a Python function to calculate fibonacci numbers:\n\n",
            ARTIFACT_START,
            "def fibonacci(n):\n",
            "    if n <= 1:\n",
            "        return n\n",
            "    return fibonacci(n-1) + fibonacci(n-2)",
            ARTIFACT_END,
            "\n\nThis uses recursion to calculate the nth fibonacci number.",
        ]

        for chunk_content in chunks:
            acc.add_chunk(AIMessageChunk(content=chunk_content))

        artifact = acc.get_artifact_text()
        assert artifact is not None
        assert "def fibonacci(n):" in artifact
        assert "return fibonacci(n-1) + fibonacci(n-2)" in artifact

        msg = acc.finalize()
        assert "Here's a Python function" in msg.content
        assert "This uses recursion" in msg.content
        assert ARTIFACT_START not in msg.content
        assert ARTIFACT_END not in msg.content

    def test_metadata_with_artifact(self):
        """Test that metadata is preserved alongside artifact content."""
        acc = AIMessageAccumulator()

        acc.add_chunk(
            AIMessageChunk(
                content=f"{ARTIFACT_START}code", additional_kwargs={"model": "claude"}
            )
        )
        acc.add_chunk(
            AIMessageChunk(
                content=f"{ARTIFACT_END}", response_metadata={"stop_reason": "end_turn"}
            )
        )

        assert acc.get_artifact_text() == "code"

        msg = acc.finalize()
        assert msg.additional_kwargs["model"] == "claude"
        assert msg.response_metadata["stop_reason"] == "end_turn"

    def test_interleaved_text_and_artifacts(self):
        """Test text and artifacts interleaved."""
        acc = AIMessageAccumulator()

        acc.add_chunk(
            AIMessageChunk(
                content=f"First text {ARTIFACT_START}artifact1{ARTIFACT_END} middle {ARTIFACT_START}artifact2{ARTIFACT_END} last"
            )
        )
        assert acc.get_assistant_text() == "First text  middle  last"
        assert acc.get_artifact_text() == "artifact1artifact2"

        msg = acc.finalize()
        assert msg.content == "First text  middle  last artifact1artifact2"

    def test_real_streaming_pattern(self):
        """Test a realistic streaming pattern with small chunks."""
        acc = AIMessageAccumulator()

        # Simulate realistic small chunks
        full_text = f"I'll create that for you: {ARTIFACT_START}const x = 42;{ARTIFACT_END} There you go!"
        chunk_size = 5

        for i in range(0, len(full_text), chunk_size):
            chunk = full_text[i : i + chunk_size]
            acc.add_chunk(AIMessageChunk(content=chunk))

        assert acc.get_assistant_text() == "I'll create that for you:  There you go!"
        assert acc.get_artifact_text() == "const x = 42;"

        msg = acc.finalize()
        assert msg.content == "I'll create that for you:  There you go! const x = 42;"

    def test_reset_turn_text_drops_pre_tool_preamble(self):
        """Tool-call preambles must not be joined onto the final answer."""
        acc = AIMessageAccumulator()

        # Turn 1: Claude's preamble that accompanies its tool_calls.
        acc.add_chunk(
            AIMessageChunk(
                content="I'll load the project inspector skill.",
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
            )
        )
        acc.reset_turn_text()  # tool result arrived

        # Turn 2: another preamble before the second tool call.
        acc.add_chunk(AIMessageChunk(content="Now I'll query your project:"))
        acc.reset_turn_text()

        # Final turn: the actual answer.
        acc.add_chunk(
            AIMessageChunk(
                content="Your project has 4 walls.",
                usage_metadata={
                    "input_tokens": 20,
                    "output_tokens": 7,
                    "total_tokens": 27,
                },
            )
        )

        assert acc.get_assistant_text() == "Your project has 4 walls."
        msg = acc.finalize()
        assert msg.content == "Your project has 4 walls."
        # Usage totals span the whole run even though text was reset.
        assert msg.usage_metadata["output_tokens"] == 12

    def test_reset_turn_text_clears_partial_artifact_state(self):
        """A reset mid-artifact must not leak into the next turn's routing."""
        acc = AIMessageAccumulator()

        acc.add_chunk(AIMessageChunk(content=f"stale {ARTIFACT_START}partial"))
        acc.reset_turn_text()

        acc.add_chunk(AIMessageChunk(content="final answer"))
        assert acc.get_assistant_text() == "final answer"
        assert acc.get_artifact_text() is None

    def test_reset_turn_text_clears_tool_calls(self):
        """Tool calls before reset must not appear in the final message."""
        acc = AIMessageAccumulator()

        tool_call = {
            "id": "123",
            "name": "search",
            "args": {"query": "test"},
            "type": "tool_call",
        }
        acc.add_chunk(
            AIMessageChunk(content="I'll search for that.", tool_calls=[tool_call])
        )
        acc.reset_turn_text()  # tool result arrived

        acc.add_chunk(AIMessageChunk(content="Here's what I found."))

        msg = acc.finalize()
        assert msg.content == "Here's what I found."
        assert msg.tool_calls == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
