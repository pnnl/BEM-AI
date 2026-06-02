from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from automa_ai.checkpoint.defaults import (
    DEFAULT_REDIS_CHECKPOINT_TTL_SECONDS,
    DEFAULT_REDIS_HEALTH_CHECK_INTERVAL,
    DEFAULT_REDIS_MAX_CHECKPOINTS_PER_THREAD,
    DEFAULT_REDIS_REFRESH_TTL_ON_READ,
    DEFAULT_REDIS_RETRY_ON_TIMEOUT,
    DEFAULT_REDIS_SOCKET_CONNECT_TIMEOUT,
    DEFAULT_REDIS_SOCKET_TIMEOUT,
)


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
    """Declarative checkpointer configuration for LangGraph chat agents.

    Available backends:
    - ``default``: in-memory LangGraph saver
    - ``redis_plain``: AUTOMA-AI saver implemented with core Redis commands only;
      use a single-shard Redis/Valkey target because Redis Cluster mode can
      CROSSSLOT the saver's multi-key checkpoint lifecycle operations
    - ``redis_stack``: LangGraph Redis saver requiring RediSearch and RedisJSON
    - ``agentcore``: AWS AgentCore persistent memory saver
    """

    type: Literal["default", "redis_plain", "redis_stack", "agentcore"] = Field(
        default="default"
    )

    # Redis
    redis_url: str | None = None
    checkpoint_ttl_seconds: int | None = Field(
        default=DEFAULT_REDIS_CHECKPOINT_TTL_SECONDS, ge=1
    )
    # Retention is counted by distinct LangGraph metadata["step"] groups in
    # PlainRedisSaver, not by raw checkpoint records. The field name is kept for
    # compatibility with existing checkpointer configs.
    max_checkpoints_per_thread: int | None = Field(
        default=DEFAULT_REDIS_MAX_CHECKPOINTS_PER_THREAD, ge=1
    )
    refresh_ttl_on_read: bool = DEFAULT_REDIS_REFRESH_TTL_ON_READ
    socket_timeout: float | None = Field(default=DEFAULT_REDIS_SOCKET_TIMEOUT, gt=0)
    socket_connect_timeout: float | None = Field(
        default=DEFAULT_REDIS_SOCKET_CONNECT_TIMEOUT, gt=0
    )
    health_check_interval: int | None = Field(
        default=DEFAULT_REDIS_HEALTH_CHECK_INTERVAL, ge=0
    )
    retry_on_timeout: bool = DEFAULT_REDIS_RETRY_ON_TIMEOUT

    # AgentCore
    memory_id: str | None = None
    region: str | None = None

    def _uses_custom_plain_redis_options(self) -> bool:
        """Return True when PlainRedisSaver-specific settings differ from defaults.

        These settings are implemented only by ``PlainRedisSaver``. The helper
        keeps validation readable and prevents redis_stack/default/agentcore from
        silently accepting options they do not use.
        """
        return any(
            [
                self.checkpoint_ttl_seconds
                != DEFAULT_REDIS_CHECKPOINT_TTL_SECONDS,
                self.max_checkpoints_per_thread
                != DEFAULT_REDIS_MAX_CHECKPOINTS_PER_THREAD,
                self.refresh_ttl_on_read is not DEFAULT_REDIS_REFRESH_TTL_ON_READ,
                self.socket_timeout != DEFAULT_REDIS_SOCKET_TIMEOUT,
                self.socket_connect_timeout
                != DEFAULT_REDIS_SOCKET_CONNECT_TIMEOUT,
                self.health_check_interval != DEFAULT_REDIS_HEALTH_CHECK_INTERVAL,
                self.retry_on_timeout is not DEFAULT_REDIS_RETRY_ON_TIMEOUT,
            ]
        )

    @field_validator("redis_url")
    @classmethod
    def _validate_redis_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_redis_url(value)

    @model_validator(mode="after")
    def _validate_type_specific_fields(self) -> "CheckpointerConfig":
        if self.type in {"redis_plain", "redis_stack"}:
            if not self.redis_url:
                raise ValueError(
                    "redis_url is required when checkpointer type is 'redis_plain' or 'redis_stack'."
                )
            if self.memory_id or self.region:
                raise ValueError(
                    "memory_id/region are not valid for Redis checkpointers."
                )
            # Redis Stack uses LangGraph's RedisSaver, not PlainRedisSaver, so it
            # cannot honor the plain Redis lifecycle/connection options added here.
            if self.type == "redis_stack" and self._uses_custom_plain_redis_options():
                raise ValueError(
                    "Plain Redis lifecycle and connection options are only supported by redis_plain."
                )

        elif self.type == "agentcore":
            if not self.memory_id:
                raise ValueError(
                    "memory_id is required when checkpointer type is 'agentcore'."
                )
            if any(
                [
                    self.redis_url,
                    self._uses_custom_plain_redis_options(),
                ]
            ):
                raise ValueError(
                    "Redis checkpointer fields are not valid for agentcore checkpointer."
                )

        else:  # default
            if any(
                [
                    self.redis_url,
                    self.memory_id,
                    self.region,
                    self._uses_custom_plain_redis_options(),
                ]
            ):
                raise ValueError(
                    "No extra fields are allowed when checkpointer type is 'default'."
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
