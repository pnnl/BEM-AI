"""Web search tool configuration models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SerperConfig(BaseModel):
    api_key: str | None = None
    endpoint: str = "https://google.serper.dev/search"


class FirecrawlConfig(BaseModel):
    api_key: str | None = None
    endpoint: str = "https://api.firecrawl.dev/v1/scrape"
    enabled: bool = True


class ScrapeConfig(BaseModel):
    enabled: bool = True
    max_pages: int = Field(default=5, ge=0, le=20)
    max_content_chars: int = Field(default=8000, ge=500)


class RerankConfig(BaseModel):
    provider: Literal["jina", "cohere", "opensource", "none"] = "opensource"
    top_k: int = Field(default=5, ge=1, le=50)
    jina_api_key: str | None = None
    cohere_api_key: str | None = None


class WebSearchToolConfig(BaseModel):
    provider: Literal["auto", "serper", "opensource"] = "auto"
    timeout_s: float = Field(default=8.0, gt=0)
    default_max_results: int = Field(default=10, ge=1, le=50)
    user_agent: str = "automa-ai-web-search/0.1"
    serper: SerperConfig = Field(default_factory=SerperConfig)
    firecrawl: FirecrawlConfig = Field(default_factory=FirecrawlConfig)
    scrape: ScrapeConfig = Field(default_factory=ScrapeConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)
