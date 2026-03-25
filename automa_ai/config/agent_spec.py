from __future__ import annotations

"""Versioned YAML agent specification support.

This is an additive bridge that maps YAML configuration to the existing
``AgentFactory`` constructor surface without replacing current Python-based paths.
"""

from pathlib import Path
from typing import Any, Literal

import yaml
from a2a.types import AgentCard
from pydantic import BaseModel, Field

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.common.mcp_registry import MCPServerConfig
from automa_ai.config.learning import LearningWorkflowConfig
from automa_ai.config.tools import ToolsConfig
from automa_ai.config.blackboard import BlackboardConfig
from automa_ai.retrieval.config import RetrieverProviderSpec
from automa_ai.skills import SkillsConfig


class AgentIdentitySpec(BaseModel):
    name: str
    description: str = ""
    instructions: str


class ModelSpec(BaseModel):
    provider: GenericLLM
    model_name: str
    base_url: str | None = None
    api_key: str | None = None
    api_version: str | None = None


class RuntimeSpec(BaseModel):
    agent_type: GenericAgentType = GenericAgentType.LANGGRAPHCHAT
    enable_metrics: bool = False
    debug: bool = False


class MCPServerSpec(BaseModel):
    name: str
    host: str
    port: int
    transport: Literal["stdio", "sse", "streamable-http"] = "sse"
    agent_cards_dir: str | None = None


class MCPConfigSpec(BaseModel):
    servers: dict[str, MCPServerSpec] = Field(default_factory=dict)


class YamlAgentSpec(BaseModel):
    """General AUTOMA-AI YAML agent spec.

    Schema is intentionally minimal and grounded in AgentFactory inputs.
    """

    spec_version: str = "v1"
    agent: AgentIdentitySpec
    model: ModelSpec
    runtime: RuntimeSpec = Field(default_factory=RuntimeSpec)

    mcp: MCPConfigSpec | None = None
    retriever: RetrieverProviderSpec | dict[str, Any] | None = None
    memory: dict[str, Any] | None = None
    skills: SkillsConfig | dict[str, Any] | None = None
    tools: ToolsConfig | dict[str, Any] | list[dict[str, Any]] | None = None
    blackboard: BlackboardConfig | dict[str, Any] | None = None
    learning: LearningWorkflowConfig | dict[str, Any] | None = None

    def to_agent_factory(self) -> AgentFactory:
        return AgentFactory(**self.to_factory_kwargs())

    def to_factory_kwargs(self) -> dict[str, Any]:
        mcp_configs: dict[str, MCPServerConfig] | None = None
        if self.mcp and self.mcp.servers:
            mcp_configs = {}
            for alias, server in self.mcp.servers.items():
                mcp_configs[alias] = MCPServerConfig(
                    name=server.name,
                    host=server.host,
                    port=server.port,
                    serve=_noop_serve,
                    transport=server.transport,
                    agent_cards_dir=server.agent_cards_dir or "/automa_ai",
                )

        learning_cfg: LearningWorkflowConfig | dict[str, Any] | None = self.learning
        if learning_cfg and not isinstance(learning_cfg, LearningWorkflowConfig):
            learning_cfg = LearningWorkflowConfig.model_validate(learning_cfg)

        return {
            "card": AgentCard(name=self.agent.name, description=self.agent.description, url=""),
            "instructions": self.agent.instructions,
            "model_name": self.model.model_name,
            "agent_type": self.runtime.agent_type,
            "chat_model": self.model.provider,
            "mcp_configs": mcp_configs,
            "retriever_spec": self.retriever,
            "memory_config": self.memory,
            "skills_config": self.skills,
            "tools_config": self.tools,
            "blackboard_config": self.blackboard,
            "model_base_url": self.model.base_url,
            "api_key": self.model.api_key,
            "api_version": self.model.api_version,
            "enable_metrics": self.runtime.enable_metrics,
            "debug": self.runtime.debug,
            "learning_config": learning_cfg,
        }

    @classmethod
    def from_yaml_file(cls, path: str | Path) -> "YamlAgentSpec":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)

    @classmethod
    def from_yaml_text(cls, text: str) -> "YamlAgentSpec":
        return cls.model_validate(yaml.safe_load(text))


def _noop_serve(*_args: Any, **_kwargs: Any) -> None:
    """Placeholder callable for MCPServerConfig in YAML-only loading mode."""
