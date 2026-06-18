import pytest
from a2a.helpers.proto_helpers import new_text_part
from google.protobuf.json_format import MessageToDict

from automa_ai.client.simple_client import SimpleClient


def test_simple_client_builds_request_from_parts():
    client = SimpleClient(agent_url="http://localhost:1234")
    parts = SimpleClient.build_multimodal_parts(
        "Describe these images",
        image_bytes=[b"fake png"],
        image_urls=["https://example.com/page.png"],
    )

    request = client._build_request_from_parts(parts, context_id="session-1")

    assert request.message.context_id == "session-1"
    assert request.message.parts[0].text == "Describe these images"
    assert request.message.parts[1].raw == b"fake png"
    assert request.message.parts[1].media_type == "image/png"
    assert request.message.parts[2].url == "https://example.com/page.png"
    assert request.message.parts[2].media_type == "image/png"
    assert request.message.message_id


def test_simple_client_builds_mixed_media_type_parts():
    parts = SimpleClient.build_multimodal_parts(
        "Describe these images",
        image_bytes=[
            (b"fake png", "image/png"),
            (b"fake jpg", "image/jpeg"),
        ],
        image_urls=[
            ("https://example.com/page.webp", "image/webp"),
            "https://example.com/page.png",
        ],
    )

    assert parts[1].raw == b"fake png"
    assert parts[1].media_type == "image/png"
    assert parts[2].raw == b"fake jpg"
    assert parts[2].media_type == "image/jpeg"
    assert parts[3].url == "https://example.com/page.webp"
    assert parts[3].media_type == "image/webp"
    assert parts[4].url == "https://example.com/page.png"
    assert parts[4].media_type == "image/png"


def test_simple_client_parts_request_leaves_context_id_unset_when_none():
    client = SimpleClient(agent_url="http://localhost:1234")

    request = client._build_request_from_parts([new_text_part("hello")])

    serialized = MessageToDict(request.message, preserving_proto_field_name=False)
    assert "contextId" not in serialized
    assert request.message.context_id == ""
    assert request.message.message_id


def test_simple_client_rejects_empty_parts_request():
    client = SimpleClient(agent_url="http://localhost:1234")

    with pytest.raises(ValueError, match="at least one A2A Part"):
        client._build_request_from_parts([])


def test_simple_client_text_request_remains_text_only():
    client = SimpleClient(agent_url="http://localhost:1234")

    request = client._build_request("hello", context_id="session-1")

    assert request.message.context_id == "session-1"
    assert len(request.message.parts) == 1
    assert request.message.parts[0].text == "hello"


@pytest.mark.asyncio
async def test_simple_client_send_message_parts_uses_parts_stream(monkeypatch):
    client = SimpleClient(agent_url="http://localhost:1234")
    captured = {}

    async def fake_stream(parts, context_id=None):
        captured["parts"] = parts
        captured["context_id"] = context_id
        yield {"result": {"kind": "task", "id": "task-1"}}

    monkeypatch.setattr(client, "_stream_serialized_parts_responses", fake_stream)

    response = await client.send_message_parts(
        [new_text_part("hello")],
        context_id="session-1",
    )

    assert captured["parts"][0].text == "hello"
    assert captured["context_id"] == "session-1"
    assert response == {"result": {"kind": "task", "id": "task-1"}}
