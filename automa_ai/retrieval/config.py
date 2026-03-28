"""Configuration objects for retrieval providers and embeddings."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class EmbeddingConfig(BaseModel):
    provider: Literal["ollama", "azure-openai", "openai"]
    model: str | None = None
    api_key: str | None = None
    api_version: str | None = None
    base_url: str | None = None
    organization: str | None = None
    project: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_s: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class RetrieverProviderSpec(BaseModel):
    provider: str | None = None
    impl: str | None = None
    top_k: int = 4
    embedding: EmbeddingConfig | None = None
    retrieval_provider_config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def _validate_provider_or_impl(self) -> "RetrieverProviderSpec":
        if not self.enabled:
            return self
        if bool(self.provider) == bool(self.impl):
            raise ValueError(
                "RetrieverProviderSpec requires exactly one of 'provider' or 'impl' when enabled."
            )
        return self
