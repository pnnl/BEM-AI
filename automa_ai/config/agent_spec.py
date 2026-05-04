"""YAML agent specification support.

This module keeps YAML loading as a thin bridge over the existing
``AgentFactory`` and ``A2AAgentServer`` runtime APIs.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Literal, TypeAlias

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.agents.remote_agent import SubAgentSpec
from automa_ai.common.agent_registry import A2AAgentServer
from automa_ai.common.mcp_registry import MCPServerConfig


class InstructionsSpec(BaseModel):
    """Instruction source for an agent."""

    text: str | None = None
    path: str | None = None

    @model_validator(mode="after")
    def _validate_single_source(self) -> "InstructionsSpec":
        if bool(self.text) == bool(self.path):
            raise ValueError("instructions requires exactly one of 'text' or 'path'.")
        return self

    def resolve(self, *, base_dir: Path) -> str:
        """Return instruction text, resolving relative file paths from ``base_dir``."""
        if self.text is not None:
            return self.text

        assert self.path is not None
        instruction_path = Path(self.path)
        if not instruction_path.is_absolute():
            instruction_path = base_dir / instruction_path
        return instruction_path.read_text(encoding="utf-8")


class ModelSpec(BaseModel):
    """Model provider configuration."""

    provider: GenericLLM
    name: str = Field(alias="model_name")
    base_url: str | None = None
    api_key: str | None = None
    api_version: str | None = None
    max_retries: int | None = None

    model_config = ConfigDict(populate_by_name=True)


class RuntimeSpec(BaseModel):
    """Agent runtime configuration."""

    agent_type: GenericAgentType = GenericAgentType.LANGGRAPHCHAT
    transient_retry_attempts: int = 0
    enable_metrics: bool = False
    debug: bool = False


class ServerSpec(BaseModel):
    """A2A server wrapper options."""

    log_dir: str = "./logs"
    base_url_path: str | None = None
    health_check_path: str = "/health"


class MCPServerSpec(BaseModel):
    """Client-side MCP server connection configuration."""

    name: str
    host: str
    port: int
    transport: Literal["stdio", "sse", "streamable-http"] = "sse"
    timeout: float | None = None
    sse_read_timeout: float | None = None
    agent_cards_dir: str = "/automa_ai"


class MCPConfigSpec(BaseModel):
    servers: dict[str, MCPServerSpec] = Field(default_factory=dict)


class SubAgentYamlSpec(BaseModel):
    name: str | None = None
    description: str | None = None
    agent_card: dict[str, Any] | None = None
    spec_path: str | None = None
    card_path: str | None = None

    @model_validator(mode="after")
    def _validate_single_card_source(self) -> "SubAgentYamlSpec":
        sources = [
            self.agent_card is not None,
            self.spec_path is not None,
            self.card_path is not None,
        ]
        if sum(sources) != 1:
            raise ValueError(
                "subagent requires exactly one of 'agent_card', 'spec_path', or 'card_path'."
            )
        return self

    def resolve_agent_card(self, *, base_dir: Path) -> dict[str, Any]:
        """Resolve the subagent card from an inline card, YAML spec, or JSON card file."""
        if self.agent_card is not None:
            return deepcopy(self.agent_card)

        if self.spec_path is not None:
            spec_path = _resolve_path(self.spec_path, base_dir=base_dir)
            return deepcopy(YamlAgentSpec.from_yaml_file(spec_path).agent_card)

        assert self.card_path is not None
        card_path = _resolve_path(self.card_path, base_dir=base_dir)
        return json.loads(card_path.read_text(encoding="utf-8"))

    def to_subagent_spec(self, *, base_dir: Path) -> SubAgentSpec:
        """Convert the YAML subagent entry into the runtime delegation spec."""
        agent_card = self.resolve_agent_card(base_dir=base_dir)
        name = self.name or agent_card.get("name")
        description = self.description or agent_card.get("description")
        if not name:
            raise ValueError(
                "subagent name is required or must exist on the agent card."
            )
        if description is None:
            raise ValueError(
                "subagent description is required or must exist on the agent card."
            )
        return SubAgentSpec(
            name=name,
            description=description,
            agent_card=agent_card,
        )


class YamlAgentSpec(BaseModel):
    """One YAML file describing one AUTOMA-AI agent server."""

    spec_version: Literal["v1"] = "v1"
    agent_card: dict[str, Any]
    instructions: InstructionsSpec
    model: ModelSpec
    runtime: RuntimeSpec = Field(default_factory=RuntimeSpec)
    server: ServerSpec = Field(default_factory=ServerSpec)

    mcp: MCPConfigSpec | None = None
    subagents: list[SubAgentYamlSpec] = Field(default_factory=list)
    retriever: dict[str, Any] | None = None
    memory: dict[str, Any] | None = None
    skills: dict[str, Any] | None = None
    tools: dict[str, Any] | list[dict[str, Any]] | None = None
    blackboard: dict[str, Any] | None = None
    checkpointer: dict[str, Any] | str | None = None

    _base_dir: Path = Path.cwd()

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_agent_card(self) -> "YamlAgentSpec":
        if not self.agent_card.get("name"):
            raise ValueError("agent_card.name is required.")
        interfaces = self.agent_card.get("supportedInterfaces")
        if not interfaces:
            raise ValueError(
                "agent_card.supportedInterfaces must contain at least one interface."
            )
        if not interfaces[0].get("url"):
            raise ValueError("agent_card.supportedInterfaces[0].url is required.")
        return self

    @classmethod
    def from_yaml_file(cls, path: str | Path) -> "YamlAgentSpec":
        """Load and validate one agent spec from a YAML file.

        The YAML file's directory is retained so relative instruction paths can
        be resolved later, when the factory or server is built.
        """
        spec_path = Path(path)
        data = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        if data is None:
            raise ValueError(f"YAML agent spec is empty: {spec_path}")
        spec = cls.model_validate(data)
        spec._base_dir = spec_path.resolve().parent
        return spec

    @classmethod
    def from_yaml_text(
        cls,
        text: str,
        *,
        base_dir: str | Path | None = None,
    ) -> "YamlAgentSpec":
        """Load and validate one agent spec from YAML text.

        ``base_dir`` is only needed when the spec uses file-backed instructions
        with a relative path.
        """
        data = yaml.safe_load(text)
        if data is None:
            raise ValueError("YAML agent spec is empty.")
        spec = cls.model_validate(data)
        if base_dir is not None:
            spec._base_dir = Path(base_dir).resolve()
        return spec

    def resolve_instructions(self) -> str:
        """Return the final system instructions passed into ``AgentFactory``."""
        return self.instructions.resolve(base_dir=self._base_dir)

    def to_factory_kwargs(self) -> dict[str, Any]:
        """Map this YAML spec onto the existing ``AgentFactory`` constructor.

        This method intentionally avoids creating agents or servers. It is useful
        for tests, inspection, and code paths that need to add or override kwargs
        before constructing the factory.
        """
        mcp_configs: dict[str, MCPServerConfig] | None = None
        if self.mcp and self.mcp.servers:
            mcp_configs = {
                alias: MCPServerConfig(
                    name=server.name,
                    host=server.host,
                    port=server.port,
                    serve=_noop_serve,
                    transport=server.transport,
                    timeout=server.timeout,
                    sse_read_timeout=server.sse_read_timeout,
                    agent_cards_dir=server.agent_cards_dir,
                )
                for alias, server in self.mcp.servers.items()
            }

        return {
            "card": deepcopy(self.agent_card),
            "instructions": self.resolve_instructions(),
            "model_name": self.model.name,
            "agent_type": self.runtime.agent_type,
            "chat_model": self.model.provider,
            "mcp_configs": mcp_configs,
            "retriever_spec": self.retriever,
            "subagent_config": [
                item.to_subagent_spec(base_dir=self._base_dir)
                for item in self.subagents
            ]
            or None,
            "memory_config": self.memory,
            "skills_config": self.skills,
            "tools_config": self.tools,
            "blackboard_config": self.blackboard,
            "checkpointer_config": self.checkpointer,
            "model_base_url": self.model.base_url,
            "api_key": self.model.api_key,
            "api_version": self.model.api_version,
            "model_max_retries": self.model.max_retries,
            "transient_retry_attempts": self.runtime.transient_retry_attempts,
            "enable_metrics": self.runtime.enable_metrics,
            "debug": self.runtime.debug,
        }

    def to_agent_factory(self) -> AgentFactory:
        """Build an ``AgentFactory`` from the YAML spec."""
        return AgentFactory(**self.to_factory_kwargs())

    def to_a2a_server(self) -> A2AAgentServer:
        """Build a single ``A2AAgentServer`` from the YAML spec.

        Host, port, and default base path are derived by ``A2AAgentServer`` from
        ``agent_card.supportedInterfaces[0].url``.
        """
        return A2AAgentServer(
            agent_builder=self.to_agent_factory(),
            card=deepcopy(self.agent_card),
            log_dir=self.server.log_dir,
            base_url_path=self.server.base_url_path,
            health_check_path=self.server.health_check_path,
        )


YamlAgentSource: TypeAlias = str | Path | YamlAgentSpec


def _resolve_agent_spec(source: YamlAgentSource) -> YamlAgentSpec:
    """Normalize a YAML path or pre-loaded spec into ``YamlAgentSpec``."""
    if isinstance(source, YamlAgentSpec):
        return source
    return YamlAgentSpec.from_yaml_file(source)


def _resolve_path(path: str, *, base_dir: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = base_dir / resolved
    return resolved


def load_agent_factory_from_yaml(source: YamlAgentSource) -> AgentFactory:
    """Build an ``AgentFactory`` from a YAML path or existing ``YamlAgentSpec``."""
    return _resolve_agent_spec(source).to_agent_factory()


def load_a2a_server_from_yaml(source: YamlAgentSource) -> A2AAgentServer:
    """Build one bootable ``A2AAgentServer`` from a YAML path or spec object."""
    return _resolve_agent_spec(source).to_a2a_server()


def _noop_serve(*_args: Any, **_kwargs: Any) -> None:
    """Guardrail for YAML MCP entries, which are client configs only."""
    raise RuntimeError(
        "YAML MCP entries configure agent client connections only. "
        "Start MCP servers separately with MCPServerManager."
    )
