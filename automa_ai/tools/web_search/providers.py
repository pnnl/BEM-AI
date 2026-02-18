from __future__ import annotations

import asyncio
from typing import Any

import httpx


def _normalize_result(item: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "title": item.get("title") or item.get("heading") or "",
        "url": item.get("link") or item.get("url") or "",
        "snippet": item.get("snippet") or item.get("body") or "",
        "source": source,
    }


async def serper_search(
    client: httpx.AsyncClient,
    query: str,
    api_key: str,
    max_results: int,
    time_range: str | None = None,
    endpoint: str = "https://google.serper.dev/search",
) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {"q": query, "num": max_results}
    if time_range:
        payload["tbs"] = time_range
    resp = await client.post(
        endpoint,
        headers={"X-API-KEY": api_key},
        json=payload,
    )
    if resp.status_code == 401:
        raise ValueError("Serper authentication failed (401).")
    if resp.status_code >= 400:
        raise RuntimeError(f"Serper request failed with status {resp.status_code}.")
    data = resp.json()
    return [_normalize_result(x, "serper") for x in (data.get("organic") or [])][
        :max_results
    ]


async def duckduckgo_search(
    query: str, max_results: int, region: str | None = None
) -> list[dict[str, Any]]:
    try:
        from duckduckgo_search import DDGS
    except Exception as exc:
        raise RuntimeError(
            "Open-source web search requires the 'duckduckgo_search' package. Install with automa_ai[web]."
        ) from exc

    def _run() -> list[dict[str, Any]]:
        with DDGS() as ddgs:
            return list(ddgs.text(query, region=region, max_results=max_results))

    rows = await asyncio.to_thread(_run)
    return [_normalize_result(x, "duckduckgo") for x in rows][:max_results]


async def firecrawl_scrape(
    client: httpx.AsyncClient,
    url: str,
    api_key: str,
    endpoint: str = "https://api.firecrawl.dev/v1/scrape",
) -> str:
    resp = await client.post(
        endpoint,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"url": url, "formats": ["markdown"]},
    )
    if resp.status_code == 401:
        raise ValueError("Firecrawl authentication failed (401).")
    if resp.status_code >= 400:
        raise RuntimeError(f"Firecrawl request failed with status {resp.status_code}.")
    data = resp.json().get("data") or {}
    return data.get("markdown") or data.get("content") or ""
