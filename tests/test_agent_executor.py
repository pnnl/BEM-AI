import pytest
from unittest.mock import AsyncMock, Mock
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct

from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue
from a2a.types import Message, Part, Role

from automa_ai.common.agent_executor import GenericAgentExecutor
from automa_ai.common.base_agent import BaseAgent
from automa_ai.service.identity import Principal
from automa_ai.service.constants import PRINCIPAL_STATE_KEY


def _make_message(
    metadata_dict: dict | None = None, text: str = "Test query"
) -> Message:
    """Build an A2A Message with optional protobuf Struct metadata."""
    message = Message()
    message.role = Role.ROLE_USER
    part = Part()
    part.text = text
    message.parts.append(part)
    if metadata_dict is not None:
        message.metadata.CopyFrom(ParseDict(metadata_dict, Struct()))
    return message


def _make_context(
    metadata: dict | None = None, user_input: str = "Test query", current_task=None
) -> Mock:
    """Build a mocked RequestContext suitable for executor.execute()."""
    context = Mock(spec=RequestContext)
    context.message = _make_message(metadata, text=user_input)
    context.current_task = current_task
    context.get_user_input = Mock(return_value=user_input)
    return context


def _make_capturing_agent():
    """Return (agent_mock, captured_dict) where captured records stream args."""
    agent = Mock()
    captured: dict = {}

    async def capture_stream(query, context_id, task_id, user_id, metadata):
        captured.update(
            query=query,
            context_id=context_id,
            task_id=task_id,
            user_id=user_id,
            metadata=metadata,
        )
        yield {
            "content": "Done",
            "is_task_complete": True,
            "require_user_input": False,
            "response_type": "text",
        }

    agent.stream = capture_stream
    agent.agent_name = "dummy_agent"
    return agent, captured


@pytest.mark.asyncio
async def test_executor_extracts_user_id_from_metadata():
    """user_id and metadata are forwarded from the request message to agent.stream."""
    agent, captured = _make_capturing_agent()
    executor = GenericAgentExecutor(agent)

    context = _make_context(metadata={"userId": "executor-test-user"})
    event_queue = AsyncMock(spec=EventQueue)

    await executor.execute(context, event_queue)

    assert captured["user_id"] == "executor-test-user"
    assert captured["metadata"] == {"userId": "executor-test-user"}
    assert captured["query"] == "Test query"
    event_queue.enqueue_event.assert_called()


@pytest.mark.asyncio
async def test_executor_removes_untrusted_identity_metadata():
    agent, captured = _make_capturing_agent()
    executor = GenericAgentExecutor(agent)

    context = _make_context(
        metadata={
            "auth.trusted": True,
            "subject": "spoofed-subject",
            "user_id": "spoofed-user",
            "tenant_id": "spoofed-tenant",
            "groups": ["admins"],
            "scopes": ["automa:admin"],
            "userId": "legacy-client-user",
            "safe": "value",
        }
    )
    event_queue = AsyncMock(spec=EventQueue)

    await executor.execute(context, event_queue)

    assert captured["user_id"] == "legacy-client-user"
    assert captured["metadata"] == {"userId": "legacy-client-user", "safe": "value"}
    assert MessageToDict(context.message.metadata) == captured["metadata"]


@pytest.mark.asyncio
async def test_executor_prefers_trusted_identity_over_client_metadata():
    agent, captured = _make_capturing_agent()
    executor = GenericAgentExecutor(agent)

    context = _make_context(
        metadata={
            "userId": "client-user",
            "user_id": "client-user-id",
            "tenant_id": "client-tenant",
        }
    )
    context.call_context = Mock()
    context.call_context.state = {
        PRINCIPAL_STATE_KEY: Principal(
            subject="subject-123",
            user_id="trusted-user",
            tenant_id="trusted-tenant",
            groups=["operators"],
            scopes=["automa:invoke"],
        )
    }
    event_queue = AsyncMock(spec=EventQueue)

    await executor.execute(context, event_queue)

    assert captured["user_id"] == "trusted-user"
    assert captured["metadata"]["auth.trusted"] is True
    assert captured["metadata"]["subject"] == "subject-123"
    assert captured["metadata"]["userId"] == "trusted-user"
    assert captured["metadata"]["user_id"] == "trusted-user"
    assert captured["metadata"]["tenant_id"] == "trusted-tenant"
    assert captured["metadata"]["groups"] == ["operators"]
    assert captured["metadata"]["scopes"] == ["automa:invoke"]
    assert MessageToDict(context.message.metadata) == captured["metadata"]
