import logging

from collections.abc import AsyncIterable
from typing import Any

import httpx

from google.protobuf.json_format import MessageToDict, MessageToJson

from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers.proto_helpers import (
    new_message,
    new_raw_part,
    new_text_message,
    new_text_part,
    new_url_part,
)
from a2a.types import (
    AgentCard,
    GetExtendedAgentCardRequest,
    Part,
    Role,
    SendMessageRequest,
    StreamResponse,
)
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH


logger = logging.getLogger(__name__)


class SimpleClient:
    def __init__(self, agent_url: str, timeout: int | None = 30) -> None:
        # Timeout default to 30 seconds but if user set to None, then
        # Simple Client will force no timeout.
        self.agent_url = agent_url
        self.timeout = timeout
        self.public_card: AgentCard | None = None

    async def initialize_agent_card(
        self, httpx_client: httpx.AsyncClient
    ) -> None:
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=self.agent_url,
        )

        try:
            logger.info(
                "Attempting to fetch public agent card from: %s%s",
                self.agent_url,
                AGENT_CARD_WELL_KNOWN_PATH,
            )
            public_card = await resolver.get_agent_card()
            logger.info("Successfully fetched public agent card:")
            logger.info(MessageToJson(public_card, indent=2))
            self.public_card = public_card

            if public_card.capabilities.extended_agent_card:
                logger.info(
                    "Public card indicates support for an extended card. "
                    "Attempting to fetch via the 1.0 client API."
                )
                try:
                    client = await create_client(
                        public_card,
                        client_config=ClientConfig(httpx_client=httpx_client),
                    )
                    extended_card = await client.get_extended_agent_card(
                        GetExtendedAgentCardRequest()
                    )
                    logger.info(
                        "Successfully fetched extended agent card:"
                    )
                    logger.info(MessageToJson(extended_card, indent=2))
                    self.public_card = extended_card
                except Exception as extended_error:
                    logger.warning(
                        "Failed to fetch extended agent card: %s. "
                        "Will proceed with the public card.",
                        extended_error,
                        exc_info=True,
                    )
            else:
                logger.info(
                    "Public card does not indicate support for an extended "
                    "card. Using the public card."
                )
        except Exception as exc:
            logger.error(
                "Critical error fetching public agent card: %s",
                exc,
                exc_info=True,
            )
            raise RuntimeError(
                "Failed to fetch the public agent card. Cannot continue."
            ) from exc

    def _build_request(
        self, message: str, context_id: str | None = None
    ) -> SendMessageRequest:
        user_message = new_text_message(
            text=message,
            context_id=context_id,
            role=Role.ROLE_USER,
        )
        return SendMessageRequest(message=user_message)

    @staticmethod
    def build_multimodal_parts(
        text: str,
        *,
        image_bytes: list[bytes | tuple[bytes, str]] | None = None,
        image_urls: list[str | tuple[str, str]] | None = None,
        media_type: str = "image/png",
    ) -> list[Part]:
        """Build A2A parts for one text prompt plus optional image attachments.

        Bare ``bytes`` and URL strings use ``media_type``. To mix image types,
        pass ``(payload, media_type)`` tuples, for example
        ``[(png_bytes, "image/png"), (jpeg_bytes, "image/jpeg")]``.
        """
        parts = [new_text_part(text)]
        parts.extend(
            _new_image_raw_part(image, default_media_type=media_type)
            for image in image_bytes or []
        )
        parts.extend(
            _new_image_url_part(url, default_media_type=media_type)
            for url in image_urls or []
        )
        return parts

    def _build_request_from_parts(
        self, parts: list[Part], context_id: str | None = None
    ) -> SendMessageRequest:
        if not parts:
            raise ValueError("parts must contain at least one A2A Part.")

        user_message = new_message(
            parts=parts,
            context_id=context_id,
            role=Role.ROLE_USER,
        )
        return SendMessageRequest(message=user_message)

    @staticmethod
    def _normalize_state(state: str | None) -> str | None:
        if state is None:
            return None

        state_map = {
            "TASK_STATE_SUBMITTED": "submitted",
            "TASK_STATE_WORKING": "working",
            "TASK_STATE_INPUT_REQUIRED": "input-required",
            "TASK_STATE_AUTH_REQUIRED": "auth-required",
            "TASK_STATE_COMPLETED": "completed",
            "TASK_STATE_CANCELED": "canceled",
            "TASK_STATE_FAILED": "failed",
            "TASK_STATE_REJECTED": "rejected",
        }
        return state_map.get(state, state)

    @classmethod
    def _annotate_parts(cls, payload: Any) -> Any:
        if isinstance(payload, dict):
            normalized = {key: cls._annotate_parts(value) for key, value in payload.items()}
            if "parts" in normalized and isinstance(normalized["parts"], list):
                normalized["parts"] = [
                    cls._annotate_parts(part) for part in normalized["parts"]
                ]
            if "text" in normalized and "kind" not in normalized:
                normalized["kind"] = "text"
            elif "data" in normalized and "kind" not in normalized:
                normalized["kind"] = "data"
            elif "raw" in normalized and "kind" not in normalized:
                normalized["kind"] = "raw"
            elif "url" in normalized and "kind" not in normalized:
                normalized["kind"] = "url"
            if "status" in normalized and isinstance(normalized["status"], dict):
                normalized["status"] = cls._annotate_parts(normalized["status"])
                normalized["status"]["state"] = cls._normalize_state(
                    normalized["status"].get("state")
                )
            return normalized
        if isinstance(payload, list):
            return [cls._annotate_parts(item) for item in payload]
        return payload

    @classmethod
    def _serialize_stream_response(
        cls, response: StreamResponse
    ) -> dict[str, Any]:
        kind = None
        payload: dict[str, Any] = {}
        if response.HasField("status_update"):
            kind = "status-update"
            payload = MessageToDict(
                response.status_update, preserving_proto_field_name=False
            )
        elif response.HasField("artifact_update"):
            kind = "artifact-update"
            payload = MessageToDict(
                response.artifact_update, preserving_proto_field_name=False
            )
        elif response.HasField("task"):
            kind = "task"
            payload = MessageToDict(
                response.task, preserving_proto_field_name=False
            )
        elif response.HasField("message"):
            kind = "message"
            payload = MessageToDict(
                response.message, preserving_proto_field_name=False
            )

        payload = cls._annotate_parts(payload)
        if kind is not None:
            payload["kind"] = kind
            return {"result": payload}
        return {}

    async def _stream_serialized_responses(
        self,
        message: str,
        context_id: str | None = None,
    ) -> AsyncIterable[dict[str, Any]]:
        request = self._build_request(message, context_id=context_id)
        async for chunk in self._stream_serialized_request(request):
            yield chunk

    async def _stream_serialized_parts_responses(
        self,
        parts: list[Part],
        context_id: str | None = None,
    ) -> AsyncIterable[dict[str, Any]]:
        request = self._build_request_from_parts(parts, context_id=context_id)
        async for chunk in self._stream_serialized_request(request):
            yield chunk

    async def _stream_serialized_request(
        self,
        request: SendMessageRequest,
    ) -> AsyncIterable[dict[str, Any]]:
        timeout = httpx.Timeout(None) if self.timeout is None else self.timeout
        async with httpx.AsyncClient(timeout=timeout) as httpx_client:
            await self.initialize_agent_card(httpx_client=httpx_client)
            client = await create_client(
                self.public_card,
                client_config=ClientConfig(httpx_client=httpx_client),
            )
            logger.info("A2A client initialized.")

            async for chunk in client.send_message(request):
                yield self._serialize_stream_response(chunk)

    async def send_message(
        self, message: str, context_id: str | None = None
    ) -> dict[str, Any]:
        last_response: dict[str, Any] = {}
        async for chunk in self._stream_serialized_responses(
            message, context_id=context_id
        ):
            last_response = chunk
        return last_response

    async def send_message_parts(
        self, parts: list[Part], context_id: str | None = None
    ) -> dict[str, Any]:
        last_response: dict[str, Any] = {}
        async for chunk in self._stream_serialized_parts_responses(
            parts, context_id=context_id
        ):
            last_response = chunk
        return last_response

    async def send_multimodal_message(
        self,
        message: str,
        *,
        image_bytes: list[bytes | tuple[bytes, str]] | None = None,
        image_urls: list[str | tuple[str, str]] | None = None,
        media_type: str = "image/png",
        context_id: str | None = None,
    ) -> dict[str, Any]:
        parts = self.build_multimodal_parts(
            message,
            image_bytes=image_bytes,
            image_urls=image_urls,
            media_type=media_type,
        )
        return await self.send_message_parts(parts, context_id=context_id)

    async def send_streaming_message(
        self, message: str, context_id: str | None = None
    ) -> AsyncIterable[dict[str, Any]]:
        async for chunk in self._stream_serialized_responses(
            message, context_id=context_id
        ):
            yield chunk

    async def send_streaming_message_parts(
        self, parts: list[Part], context_id: str | None = None
    ) -> AsyncIterable[dict[str, Any]]:
        async for chunk in self._stream_serialized_parts_responses(
            parts, context_id=context_id
        ):
            yield chunk

    async def send_streaming_multimodal_message(
        self,
        message: str,
        *,
        image_bytes: list[bytes | tuple[bytes, str]] | None = None,
        image_urls: list[str | tuple[str, str]] | None = None,
        media_type: str = "image/png",
        context_id: str | None = None,
    ) -> AsyncIterable[dict[str, Any]]:
        parts = self.build_multimodal_parts(
            message,
            image_bytes=image_bytes,
            image_urls=image_urls,
            media_type=media_type,
        )
        async for chunk in self.send_streaming_message_parts(
            parts, context_id=context_id
        ):
            yield chunk


def _new_image_raw_part(
    image: bytes | tuple[bytes, str],
    *,
    default_media_type: str,
) -> Part:
    if isinstance(image, tuple):
        raw, media_type = image
        return new_raw_part(raw=raw, media_type=media_type)
    return new_raw_part(raw=image, media_type=default_media_type)


def _new_image_url_part(
    image_url: str | tuple[str, str],
    *,
    default_media_type: str,
) -> Part:
    if isinstance(image_url, tuple):
        url, media_type = image_url
        return new_url_part(url=url, media_type=media_type)
    return new_url_part(url=image_url, media_type=default_media_type)
