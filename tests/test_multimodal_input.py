import base64
from unittest.mock import AsyncMock, Mock

import pytest
from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue
from a2a.types import Message, Part, Role
from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Struct

from automa_ai.common.agent_executor import GenericAgentExecutor
from automa_ai.hook import ContextBlock, InputAssembler, TurnInputBuilder, TurnRequest


def test_input_assembler_keeps_plain_text_without_attachments():
    assembler = InputAssembler()
    turn = TurnRequest(query="Describe this", context_id="session-1")

    assert assembler.build(turn=turn, context_blocks=[]) == {
        "messages": [{"role": "user", "content": "Describe this"}]
    }


def test_input_assembler_builds_multimodal_image_content():
    assembler = InputAssembler()
    image_data = base64.b64encode(b"fake png").decode("ascii")
    turn = TurnRequest(
        query="Describe this image",
        context_id="session-1",
        attachments=[
            {
                "type": "raw",
                "mime_type": "image/png",
                "data": image_data,
                "name": "page.png",
            }
        ],
    )

    assert assembler.build(
        turn=turn,
        context_blocks=[ContextBlock(name="system", role="system", content="Be brief")],
    ) == {
        "messages": [
            {"role": "system", "content": "Be brief"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_data,
                        },
                    },
                ],
            },
        ]
    }


@pytest.mark.asyncio
async def test_turn_input_builder_moves_attachments_out_of_metadata():
    image_data = base64.b64encode(b"fake png").decode("ascii")
    metadata = {
        "source": "test",
        "attachments": [
            {
                "type": "raw",
                "mime_type": "image/png",
                "data": image_data,
                "name": "page.png",
            }
        ],
    }
    builder = TurnInputBuilder.default()

    turn_inputs = await builder.build_inputs(
        query="Describe this image",
        context_id="session-1",
        metadata=metadata,
    )

    assert turn_inputs.turn.metadata == {"source": "test"}
    assert turn_inputs.turn.attachments == metadata["attachments"]
    assert turn_inputs.inputs["messages"][0]["content"][1]["source"] == {
        "type": "base64",
        "media_type": "image/png",
        "data": image_data,
    }


def _make_multimodal_message() -> Message:
    message = Message()
    message.role = Role.ROLE_USER
    message.parts.append(Part(text="Describe this image"))
    message.parts.append(
        Part(raw=b"fake png", media_type="image/png", filename="page.png")
    )
    message.metadata.CopyFrom(ParseDict({"userId": "user-1"}, Struct()))
    return message


def _make_multimodal_context() -> Mock:
    context = Mock(spec=RequestContext)
    context.message = _make_multimodal_message()
    context.current_task = None
    context.get_user_input = Mock(return_value="Describe this image")
    return context


@pytest.mark.asyncio
async def test_executor_raw_image_part_flows_to_multimodal_langgraph_input():
    agent = Mock()
    agent.agent_name = "dummy_agent"
    captured = {}

    async def capture_stream(query, context_id, task_id, user_id, metadata):
        turn_inputs = await TurnInputBuilder.default().build_inputs(
            query=query,
            context_id=context_id,
            task_id=task_id,
            user_id=user_id,
            metadata=metadata,
        )
        captured.update(
            query=query,
            context_id=context_id,
            task_id=task_id,
            user_id=user_id,
            metadata=metadata,
            inputs=turn_inputs.inputs,
            turn=turn_inputs.turn,
        )
        yield {
            "content": "Done",
            "is_task_complete": True,
            "require_user_input": False,
            "response_type": "text",
        }

    agent.stream = capture_stream
    executor = GenericAgentExecutor(agent)

    await executor.execute(_make_multimodal_context(), AsyncMock(spec=EventQueue))

    assert captured["query"] == "Describe this image"
    assert captured["user_id"] == "user-1"
    expected_attachment = {
        "type": "raw",
        "mime_type": "image/png",
        "data": base64.b64encode(b"fake png").decode("ascii"),
        "name": "page.png",
    }
    assert captured["metadata"]["attachments"] == [expected_attachment]
    assert captured["turn"].attachments == [expected_attachment]
    assert captured["turn"].metadata == {"userId": "user-1"}
    assert captured["inputs"]["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": expected_attachment["data"],
                    },
                },
            ],
        }
    ]
