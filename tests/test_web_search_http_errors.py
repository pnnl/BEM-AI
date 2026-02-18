from __future__ import annotations

import httpx
import pytest

from automa_ai.tools.web_search.rerank import cohere_rerank, jina_rerank
from automa_ai.tools.web_search.scraper import oss_scrape


@pytest.mark.asyncio
async def test_jina_401_maps_to_value_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError, match="authentication failed"):
            await jina_rerank(client, "q", [{"title": "a"}], "bad-key", 1)


@pytest.mark.asyncio
async def test_cohere_401_maps_to_value_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError, match="authentication failed"):
            await cohere_rerank(client, "q", [{"title": "a"}], "bad-key", 1)


@pytest.mark.asyncio
async def test_oss_scrape_raises_on_http_error_status() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="error")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await oss_scrape(client, "https://example.com", 2000)
