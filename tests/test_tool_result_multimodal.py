from __future__ import annotations

import base64
from typing import Any

import pytest
from pydantic import BaseModel

from automa_ai.config.tools import ToolSpec
from automa_ai.telemetry.redaction import sanitize_mapping
from automa_ai.tools import ToolResult, tool
from automa_ai.tools.base import (
    BaseDefaultTool,
    content_to_safe_text,
    infer_tool_result_provider,
)
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


@pytest.mark.parametrize(
    ("module", "class_name", "expected"),
    [
        ("langchain_aws.chat_models", "ChatBedrockConverse", "bedrock"),
        ("langchain_anthropic", "ChatAnthropic", "anthropic"),
        ("langchain_google_genai", "ChatGoogleGenerativeAI", "google"),
        ("langchain_openai", "ChatOpenAI", "openai"),
        ("custom.models", "LocalChatModel", "generic"),
    ],
)
def test_tool_result_provider_is_inferred_from_model_type(
    module, class_name, expected
):
    model_type = type(class_name, (), {"__module__": module})

    assert infer_tool_result_provider(model_type()) == expected


@pytest.mark.asyncio
async def test_tool_result_with_base64_image_becomes_content_blocks():
    content = await ImageTool().as_langchain_tool().ainvoke({})

    assert content == [
        {"type": "text", "text": '{"status": "success", "page": 0}'},
        {
            "type": "image",
            "base64": base64.b64encode(b"fake png").decode("ascii"),
            "mime_type": "image/png",
        },
    ]


@pytest.mark.asyncio
async def test_tool_result_with_url_image_becomes_content_blocks():
    content = await UrlImageTool().as_langchain_tool().ainvoke({})

    assert content == [
        {"type": "text", "text": '{"status": "success"}'},
        {
            "type": "image",
            "url": "https://example.com/page.jpg",
            "mime_type": "image/jpeg",
        },
    ]


@pytest.mark.asyncio
async def test_bedrock_tool_result_uses_nested_source_image_block():
    content = await ImageTool().as_langchain_tool(
        model_provider="bedrock"
    ).ainvoke({})

    assert content[1] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.b64encode(b"fake png").decode("ascii"),
        },
    }


@pytest.mark.asyncio
async def test_openai_tool_result_stays_text_only():
    content = await ImageTool().as_langchain_tool(
        model_provider="openai"
    ).ainvoke({})

    assert content == {"status": "success", "page": 0}


@pytest.mark.asyncio
async def test_bedrock_tool_result_rejects_remote_image_url():
    with pytest.raises(ValueError, match="require inline base64"):
        await UrlImageTool().as_langchain_tool(
            model_provider="bedrock"
        ).ainvoke({})


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
            "base64": "abc",
            "mime_type": "image/png",
        },
    ]


def test_multimodal_content_projects_to_binary_free_stream_text():
    content = [
        {"type": "text", "text": '{"status":"success"}'},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "secret-base64",
            },
        },
    ]

    projected = content_to_safe_text(content)

    assert '{"status":"success"}' in projected
    assert "[image/png attachment omitted from stream]" in projected
    assert "secret-base64" not in projected


def test_nested_multimodal_payload_data_is_sanitized_for_telemetry():
    data_urls = [
        "data:image/png;base64,ghi",
        "DATA:image/png;base64,jkl",
    ]
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
                {
                    "type": "image_url",
                    "image_url": {"url": data_urls[0]},
                },
                {
                    "type": "image_url",
                    "image_url": {"url": data_urls[1]},
                },
            ]
        }
    )

    # The binary payload keys should be sanitized (length/hash only)
    assert "content" not in sanitized["tool.result"][0]["source"]["data"]
    assert sanitized["tool.result"][0]["source"]["data"]["length"] == 3
    assert "content" not in sanitized["tool.result"][1]["source"]["data"]
    assert sanitized["tool.result"][1]["source"]["data"]["length"] == 3
    assert "content" not in sanitized["tool.result"][2]["image_url"]["url"]
    assert sanitized["tool.result"][2]["image_url"]["url"]["length"] == len(data_urls[0])
    assert "content" not in sanitized["tool.result"][3]["image_url"]["url"]
    assert sanitized["tool.result"][3]["image_url"]["url"]["length"] == len(data_urls[1])
