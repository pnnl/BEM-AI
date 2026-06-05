from __future__ import annotations

from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

TOKEN_BUDGET_WINDOW_PERIODS = frozenset(
    {"lifetime", "calendar_day", "calendar_month", "rolling"}
)


class TokenUsageStoreConfig(BaseModel):
    """Persistence configuration for token usage accounting."""

    backend: str = "sqlite"
    db_path: str | None = None

    model_config = ConfigDict(extra="allow")


class TokenBudgetWindowConfig(BaseModel):
    """Time window for persisted token budget enforcement."""

    period: Literal["lifetime", "calendar_day", "calendar_month", "rolling"] = (
        "lifetime"
    )
    timezone: str = "UTC"
    rolling_seconds: int | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("period", mode="before")
    @classmethod
    def _validate_period(cls, value: Any) -> Any:
        if value not in TOKEN_BUDGET_WINDOW_PERIODS:
            known = ", ".join(sorted(TOKEN_BUDGET_WINDOW_PERIODS))
            raise ValueError(
                f"Unsupported token budget window period: {value!r}. "
                f"Use one of: {known}."
            )
        return value

    @model_validator(mode="after")
    def _validate_window(self) -> "TokenBudgetWindowConfig":
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f"Unknown token budget timezone: {self.timezone!r}. "
                "Use an IANA timezone name such as 'UTC', "
                "'America/Los_Angeles', or 'Europe/London'."
            ) from exc
        if self.period == "rolling":
            if self.rolling_seconds is None or self.rolling_seconds <= 0:
                raise ValueError(
                    "rolling_seconds must be greater than 0 for rolling token windows"
                )
        elif self.rolling_seconds is not None:
            raise ValueError(
                "rolling_seconds is only supported for rolling token windows"
            )
        return self


class TokenBudgetConfig(BaseModel):
    """Token budget and agent-loop guard configuration."""

    enabled: bool = True
    max_input_tokens: int | None = None
    reserve_output_tokens: int = 0
    max_output_tokens: int | None = None
    output_token_limit_key: str = "max_tokens"
    max_model_calls_per_turn: int | None = None
    max_tool_calls_per_turn: int | None = None
    max_session_tokens: int | None = None
    session_token_window: TokenBudgetWindowConfig | None = None
    max_user_tokens: int | None = None
    user_token_window: TokenBudgetWindowConfig | None = None
    trim_strategy: Literal["first", "last"] = "last"
    allow_partial: bool = True
    summarize_when_tokens: int | None = None
    keep_recent_messages: int = 20
    store: TokenUsageStoreConfig | None = None

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> "TokenBudgetConfig":
        return cls.model_validate(config)

    @model_validator(mode="after")
    def _validate_positive_limits(self) -> "TokenBudgetConfig":
        optional_limits = [
            "max_input_tokens",
            "max_output_tokens",
            "max_model_calls_per_turn",
            "max_tool_calls_per_turn",
            "max_session_tokens",
            "max_user_tokens",
            "summarize_when_tokens",
        ]
        for field_name in optional_limits:
            value = getattr(self, field_name)
            if value is not None and value <= 0:
                raise ValueError(f"{field_name} must be greater than 0")

        non_negative_fields = [
            "reserve_output_tokens",
            "keep_recent_messages",
        ]
        for field_name in non_negative_fields:
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(f"{field_name} must be greater than or equal to 0")
        if self.max_input_tokens is not None:
            prompt_budget = self.max_input_tokens - self.reserve_output_tokens
            if prompt_budget <= 0:
                raise ValueError(
                    "max_input_tokens must be greater than reserve_output_tokens"
                )
        return self
