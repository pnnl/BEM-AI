from __future__ import annotations

import base64
from typing import Any

import pytest
from pydantic import BaseModel

from automa_ai.config.tools import ToolSpec
from automa_ai.telemetry.redaction import sanitize_mapping
from automa_ai.tools import ToolResult, tool
from automa_ai.tools.base import BaseDefaultTool
from automa_ai.tools.registry import CUSTOM_TOOL_REGISTRY


class EmptyInput(BaseModel):
    pass


class ImageTool(BaseDefaultTool):
    type = "image_tool"

    @property
    def args_schema(self) -> type[BaseModel]:
        return EmptyInput

    @property
    def description(self) -> str:
        return "Return one image attachment."

    async def invoke(self, payload: dict[str, Any]) -> ToolResult:
        return ToolResult(
            data={"status": "success", "page": 0},
            attachments=[
                {
                    "mime_type": "image/png",
                    "data": base64.b64encode(b"fake png").decode("ascii"),
                }
            ],
        )


class UrlImageTool(BaseDefaultTool):
    type = "url_image_tool"

    @property
    def args_schema(self) -> type[BaseModel]:
        return EmptyInput

    @property
    def description(self) -> str:
        return "Return one image URL attachment."

    async def invoke(self, payload: dict[str, Any]) -> ToolResult:
        return ToolResult(
            data={"status": "success"},
            attachments=[
                {
                    "mime_type": "image/jpeg",
                    "url": "https://example.com/page.jpg",
                }
            ],
        )


class UnsupportedAttachmentTool(BaseDefaultTool):
    type = "unsupported_attachment_tool"

    @property
    def args_schema(self) -> type[BaseModel]:
        return EmptyInput

    @property
    def description(self) -> str:
        return "Return unsupported attachments."

    async def invoke(self, payload: dict[str, Any]) -> ToolResult:
        return ToolResult(
            data={"status": "success"},
            attachments=[
                {"mime_type": "application/pdf", "data": "abc"},
                "not-a-dict",
            ],
        )


def test_tool_result_is_exported_from_tools_package():
    assert ToolResult(data={"ok": True}).data == {"ok": True}


@pytest.mark.asyncio
async def test_tool_result_with_base64_image_becomes_content_blocks():
    content = await ImageTool().as_langchain_tool().ainvoke({})

    assert content == [
        {"type": "text", "text": '{"status": "success", "page": 0}'},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(b"fake png").decode("ascii"),
            },
        },
    ]


@pytest.mark.asyncio
async def test_tool_result_with_url_image_becomes_content_blocks():
    content = await UrlImageTool().as_langchain_tool().ainvoke({})

    assert content == [
        {"type": "text", "text": '{"status": "success"}'},
        {
            "type": "image_url",
            "image_url": {"url": "https://example.com/page.jpg"},
        },
    ]


@pytest.mark.asyncio
async def test_tool_result_warns_and_ignores_unsupported_attachments(caplog):
    content = await UnsupportedAttachmentTool().as_langchain_tool().ainvoke({})

    assert content == {"status": "success"}
    assert "no supported image attachments" in caplog.text


@pytest.mark.asyncio
async def test_decorated_custom_tool_can_return_tool_result():
    @tool
    def custom_image_tool() -> ToolResult:
        """Return a custom multimodal result."""
        return ToolResult(
            data={"status": "success"},
            attachments=[{"mime_type": "image/png", "data": "abc"}],
        )

    built = CUSTOM_TOOL_REGISTRY.build(ToolSpec(type=f"{__name__}.custom_image_tool"))

    content = await built.as_langchain_tool().ainvoke({})

    assert content == [
        {"type": "text", "text": '{"status": "success"}'},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "abc",
            },
        },
    ]


def test_nested_multimodal_payload_data_is_sanitized_for_telemetry():
    sanitized = sanitize_mapping(
        {
            "tool.result": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": "abc"},
                },
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": "def"},
                },
            ]
        }
    )

    # The "data" key inside "source" should be sanitized (length/hash only)
    assert "content" not in sanitized["tool.result"][0]["source"]["data"]
    assert sanitized["tool.result"][0]["source"]["data"]["length"] == 3
    assert "content" not in sanitized["tool.result"][1]["source"]["data"]
    assert sanitized["tool.result"][1]["source"]["data"]["length"] == 3
