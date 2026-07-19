"""Configuration models for automa_ai."""

from automa_ai.config.blackboard import BlackboardConfig
from automa_ai.config.checkpointer import CheckpointerConfig
from automa_ai.config.service import (
    ServiceAuthConfig,
    ServiceConfig,
    ServiceIdentityConfig,
)
from automa_ai.config.telemetry import TelemetryConfig
from automa_ai.config.token_budget import (
    TokenBudgetConfig,
    TokenBudgetWindowConfig,
    TokenUsageStoreConfig,
)
from automa_ai.config.tools import ToolSpec, ToolsConfig

__all__ = [
    "ToolSpec",
    "ToolsConfig",
    "BlackboardConfig",
    "CheckpointerConfig",
    "ServiceAuthConfig",
    "ServiceConfig",
    "ServiceIdentityConfig",
    "TelemetryConfig",
    "TokenBudgetConfig",
    "TokenBudgetWindowConfig",
    "TokenUsageStoreConfig",
    "YamlAgentSpec",
    "load_agent_factory_from_yaml",
    "load_a2a_server_from_yaml",
]


def __getattr__(name: str):
    if name in {
        "YamlAgentSpec",
        "load_agent_factory_from_yaml",
        "load_a2a_server_from_yaml",
    }:
        from automa_ai.config import agent_spec

        return getattr(agent_spec, name)
    raise AttributeError(f"module 'automa_ai.config' has no attribute {name!r}")
