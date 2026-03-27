from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator


def normalize_redis_url(redis_url: str) -> str:
    normalized = redis_url.strip()
    if not normalized:
        raise ValueError("redis_url must not be empty.")

    if "://" not in normalized:
        normalized = f"redis://{normalized}"

    parsed = urlparse(normalized)
    if parsed.scheme not in {"redis", "rediss"}:
        raise ValueError("redis_url must use redis:// or rediss://.")
    if not parsed.hostname:
        raise ValueError("redis_url must include a host.")

    return normalized


class CheckpointerConfig(BaseModel):
    """Declarative checkpointer configuration for LangGraph chat agents."""

    type: Literal["default", "redis"] = Field(default="default")
    redis_url: str | None = None

    @field_validator("redis_url")
    @classmethod
    def _validate_redis_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_redis_url(value)

    @model_validator(mode="after")
    def _validate_type_specific_fields(self) -> "CheckpointerConfig":
        if self.type == "redis":
            if not self.redis_url:
                raise ValueError(
                    "redis_url is required when checkpointer type is 'redis'."
                )
        elif self.redis_url is not None:
            raise ValueError(
                "redis_url is only supported when checkpointer type is 'redis'."
            )
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CheckpointerConfig":
        return cls.model_validate(data)

    @classmethod
    def from_value(
        cls, data: "CheckpointerConfig | dict[str, Any] | str"
    ) -> "CheckpointerConfig":
        if isinstance(data, cls):
            return data
        if isinstance(data, str):
            return cls.model_validate({"type": data})
        return cls.from_dict(data)
