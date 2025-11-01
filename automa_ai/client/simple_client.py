import logging

from typing import Any, AsyncIterable
from uuid import uuid4

import httpx

from a2a.client import A2ACardResolver, A2AClient
from a2a.types import (
    AgentCard,
    MessageSendParams,
    SendMessageRequest,
    SendStreamingMessageRequest,
)
from a2a.utils.constants import (
    AGENT_CARD_WELL_KNOWN_PATH,
    EXTENDED_AGENT_CARD_PATH,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)  # Get a logger instance

class SimpleClient:
    def __init__(self, agent_url: str, timeout: int | None =30) -> None:
        # Timeout default to 30 seconds but if user set to None, then
        # Simple Client will force no timeout.
        self.agent_url = agent_url
        self.timeout = timeout
        self.public_card: AgentCard | None = None

    async def initialize_agent_card(self, httpx_client: httpx.AsyncClient) -> None:
        # Initialize A2A Card Resolver
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=self.agent_url
        )

        # Fetch Public Agent Card and Initialize Client
        try:
            logger.info(
                f'Attempting to fetch public agent card from: {self.agent_url}{AGENT_CARD_WELL_KNOWN_PATH}'
            )

            _public_card = (
                await resolver.get_agent_card()
            )  # Fetches from default public path

            logger.info('Successfully fetched public agent card:')
            logger.info(
                _public_card.model_dump_json(indent=2, exclude_none=True)
            )
            self.public_card = _public_card

            if _public_card.supports_authenticated_extended_card:
                try:
                    logger.info(
                        f'\nPublic card supports authenticated extended card. Attempting to fetch from: {self.agent_url}{EXTENDED_AGENT_CARD_PATH}'
                    )
                    auth_headers_dict = {
                        'Authorization': 'Bearer dummy-token-for-extended-card'
                    }
                    _extended_card = await resolver.get_agent_card(
                        relative_card_path=EXTENDED_AGENT_CARD_PATH,
                        http_kwargs={'headers': auth_headers_dict},
                    )
                    logger.info(
                        'Successfully fetched authenticated extended agent card:'
                    )
                    logger.info(
                        _extended_card.model_dump_json(
                            indent=2, exclude_none=True
                        )
                    )
                    self.public_card = (
                        _extended_card  # Update to use the extended card
                    )
                    logger.info(
                        '\nUsing AUTHENTICATED EXTENDED agent card for client initialization.'
                    )
                except Exception as e_extended:
                    logger.warning(
                        f'Failed to fetch extended agent card: {e_extended}. Will proceed with public card.',
                        exc_info=True,
                    )
            elif (
                    _public_card
            ):  # supports_authenticated_extended_card is False or None
                logger.info(
                    '\nPublic card does not indicate support for an extended card. Using public card.'
                )
        except Exception as e:
            logger.error(
                f'Critical error fetching public agent card: {e}', exc_info=True
            )
            raise RuntimeError(
                'Failed to fetch the public agent card. Cannot continue.'
            ) from e

    async def send_message(self, message: str) -> None:
        if self.timeout is None:
            timeout = httpx.Timeout(None)
        else:
            timeout = self.timeout
        async with httpx.AsyncClient(timeout=timeout) as httpx_client:
            # Initialize the agent card
            await self.initialize_agent_card(httpx_client=httpx_client)
            # --8<-- [start:send_message]
            client = A2AClient(
                httpx_client=httpx_client, agent_card=self.public_card
            )
            logger.info('A2AClient initialized.')

            send_message_payload: dict[str, Any] = {
                'message': {
                    'role': 'user',
                    'parts': [
                        {'kind': 'text', 'text': message}
                    ],
                    'messageId': uuid4().hex,
                },
            }
            request = SendMessageRequest(
                id=str(uuid4()), params=MessageSendParams(**send_message_payload)
            )

            response = await client.send_message(request)
            print(response)
            return response.model_dump(mode='json', exclude_none=True)


    async def send_streaming_message(self, message: str) -> AsyncIterable[dict[str, Any]]:
        if self.timeout is None:
            timeout = httpx.Timeout(None)
        else:
            timeout = self.timeout
        async with httpx.AsyncClient(timeout=timeout) as httpx_client:
            # Initialize the agent card
            await self.initialize_agent_card(httpx_client=httpx_client)
            # start:send_message_streaming
            client = A2AClient(
                httpx_client=httpx_client, agent_card=self.public_card
            )
            logger.info('A2AClient initialized.')

            send_message_payload: dict[str, Any] = {
                'message': {
                    'role': 'user',
                    'parts': [
                        {'kind': 'text', 'text': message}
                    ],
                    'messageId': uuid4().hex,
                },
            }

            streaming_request = SendStreamingMessageRequest(
                id=str(uuid4()), params=MessageSendParams(**send_message_payload)
            )

            stream_response = client.send_message_streaming(streaming_request)

            async for chunk in stream_response:
                yield chunk.model_dump(mode='json', exclude_none=True)
        # end:send_message_streaming