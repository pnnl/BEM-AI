"""Web search default tool."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from automa_ai.tools.base import BaseDefaultTool
from automa_ai.tools.web_search.config import WebSearchToolConfig
from automa_ai.tools.web_search.providers import (
    duckduckgo_search,
    firecrawl_scrape,
    serper_search,
)
from automa_ai.tools.web_search.rerank import bm25_scores, cohere_rerank, jina_rerank
from automa_ai.tools.web_search.scraper import oss_scrape


class WebSearchInput(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)
    max_results: int = Field(default=10, ge=1, le=50)
    time_range: str | None = None
    language: str | None = None
    region: str | None = None
    scrape: bool = True
    include_raw_content: bool = False


class WebSearchTool(BaseDefaultTool):
    type = "web_search"

    def __init__(self, config: WebSearchToolConfig):
        self.config = config

    @property
    def args_schema(self) -> type[BaseModel]:
        return WebSearchInput

    @property
    def description(self) -> str:
        return "Search the web, optionally scrape pages, and rerank results."

    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        args = WebSearchInput.model_validate(payload)
        warnings: list[str] = []
        timings = {"search_ms": 0, "scrape_ms": 0, "rerank_ms": 0}
        async with httpx.AsyncClient(
            timeout=self.config.timeout_s,
            headers={"User-Agent": self.config.user_agent},
        ) as client:
            t0 = time.perf_counter()
            provider = self._select_search_provider()
            if provider == "serper":
                rows = await serper_search(
                    client=client,
                    query=args.query,
                    api_key=self.config.serper.api_key or "",
                    max_results=args.max_results,
                    time_range=args.time_range,
                    endpoint=self.config.serper.endpoint,
                )
            else:
                rows = await duckduckgo_search(
                    args.query, args.max_results, args.region
                )
            timings["search_ms"] = int((time.perf_counter() - t0) * 1000)

            if args.scrape and self.config.scrape.enabled:
                t1 = time.perf_counter()
                urls: set[str] = set()
                for row in rows:
                    url = row.get("url")
                    if not self._is_valid_http_url(url) or url in urls:
                        continue
                    urls.add(url)
                    if len(urls) >= self.config.scrape.max_pages:
                        break
                for row in rows:
                    url = row.get("url")
                    if url not in urls:
                        continue
                    try:
                        if (
                            self.config.firecrawl.enabled
                            and self.config.firecrawl.api_key
                        ):
                            row["content"] = await firecrawl_scrape(
                                client,
                                url,
                                self.config.firecrawl.api_key,
                                endpoint=self.config.firecrawl.endpoint,
                            )
                        else:
                            row["content"] = await oss_scrape(
                                client, url, self.config.scrape.max_content_chars
                            )
                    except Exception as exc:
                        warnings.append(f"Failed to scrape {url}: {exc}")
                timings["scrape_ms"] = int((time.perf_counter() - t1) * 1000)

            t2 = time.perf_counter()
            try:
                rows, reranker_used = await self._rerank(
                    client, args.query, rows, args.top_k, warnings
                )
            except Exception as exc:
                warnings.append(f"Rerank failed: {exc}")
                reranker_used = "none"
                rows = rows[: args.top_k]
            timings["rerank_ms"] = int((time.perf_counter() - t2) * 1000)

            if not args.include_raw_content:
                for row in rows:
                    row.pop("content", None)

            return {
                "results": rows,
                "meta": {
                    "provider_used": provider,
                    "reranker_used": reranker_used,
                    "timings": timings,
                    "warnings": warnings,
                },
            }

    def _select_search_provider(self) -> str:
        if self.config.provider == "serper" or (
            self.config.provider == "auto" and self.config.serper.api_key
        ):
            return "serper"
        return "opensource"

    async def _rerank(
        self,
        client: httpx.AsyncClient,
        query: str,
        rows: list[dict[str, Any]],
        top_k: int,
        warnings: list[str],
    ) -> tuple[list[dict[str, Any]], str]:
        provider = self.config.rerank.provider
        order_scores: list[tuple[int, float]]
        reranker_used = provider

        if provider == "jina":
            if not self.config.rerank.jina_api_key:
                warnings.append(
                    "Rerank provider 'jina' is configured but no API key was provided; falling back to opensource BM25 rerank."
                )
                reranker_used = "opensource"
                order_scores = self._opensource_rerank(query, rows, top_k)
            else:
                order_scores = await jina_rerank(
                    client, query, rows, self.config.rerank.jina_api_key, top_k
                )
        elif provider == "cohere":
            if not self.config.rerank.cohere_api_key:
                warnings.append(
                    "Rerank provider 'cohere' is configured but no API key was provided; falling back to opensource BM25 rerank."
                )
                reranker_used = "opensource"
                order_scores = self._opensource_rerank(query, rows, top_k)
            else:
                order_scores = await cohere_rerank(
                    client, query, rows, self.config.rerank.cohere_api_key, top_k
                )
        elif provider == "none":
            return rows[:top_k], "none"
        else:
            reranker_used = "opensource"
            order_scores = self._opensource_rerank(query, rows, top_k)

        out: list[dict[str, Any]] = []
        for idx, score in order_scores:
            row = dict(rows[idx])
            row["score"] = score
            out.append(row)
        return out, reranker_used

    @staticmethod
    def _opensource_rerank(
        query: str, rows: list[dict[str, Any]], top_k: int
    ) -> list[tuple[int, float]]:
        scores = bm25_scores(query, rows)
        order_scores = list(enumerate(scores))
        order_scores.sort(key=lambda x: x[1], reverse=True)
        return order_scores[:top_k]

    @staticmethod
    def _is_valid_http_url(url: str | None) -> bool:
        if not url:
            return False
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def build_web_search_tool(config: dict[str, Any], _runtime_deps: Any) -> WebSearchTool:
    return WebSearchTool(WebSearchToolConfig.model_validate(config))
