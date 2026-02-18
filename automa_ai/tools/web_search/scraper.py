from __future__ import annotations

import asyncio

import httpx


async def extract_text(html: str) -> str:
    try:
        import trafilatura

        text = await asyncio.to_thread(trafilatura.extract, html)
        if text:
            return text
    except Exception:
        # Gracefully fall back to BeautifulSoup if trafilatura is unavailable
        # or fails to extract readable text.
        pass

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator=" ", strip=True)


async def oss_scrape(client: httpx.AsyncClient, url: str, max_chars: int) -> str:
    response = await client.get(url, follow_redirects=True)
    response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        return ""
    raw = response.text[: max_chars * 4]
    text = await extract_text(raw)
    return text[:max_chars]
