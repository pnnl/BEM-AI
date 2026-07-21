"""YAML agent specification support.

This module keeps YAML loading as a thin bridge over the existing
``AgentFactory`` and ``A2AAgentServer`` runtime APIs.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
from typing import Any, Literal, TypeAlias

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.agents.remote_agent import SubAgentSpec
from automa_ai.common.agent_registry import A2AAgentServer, normalize_a2a_card_for_server
from automa_ai.common.mcp_registry import MCPServerConfig
from automa_ai.config.a2a_auth import A2AClientAuthConfig
from automa_ai.config.service import ServiceConfig


_ENV_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_ENV_PLACEHOLDER_KEY_NAMES = {
    "api_key",
    "access_token",
    "refresh_token",
    "token",
    "password",
    "secret",
    "client_secret",
    "private_key",
}
_ENV_PLACEHOLDER_KEY_SUFFIXES = (
    "_api_key",
    "_token",
    "_password",
    "_secret",
    "_secret_key",
    "_access_key",
    "_private_key",
)


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
    debug: bool = False


class AgentIdentitySpec(BaseModel):
    """Runtime identity for an agent that is not necessarily A2A-served."""

    name: str
    description: str
    version: str | None = None


class A2ASpec(BaseModel):
    """Optional public A2A configuration for a YAML-defined agent."""

    url: str
    protocol_binding: str = Field(default="JSONRPC", alias="protocolBinding")
    protocol_version: str = Field(default="1.0", alias="protocolVersion")
    version: str | None = None
    default_input_modes: list[str] = Field(
        default_factory=lambda: ["text"], alias="defaultInputModes"
    )
    default_output_modes: list[str] = Field(
        default_factory=lambda: ["text"], alias="defaultOutputModes"
    )
    capabilities: dict[str, Any] = Field(default_factory=dict)
    skills: list[dict[str, Any]] | None = None

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


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
    auth: A2AClientAuthConfig | None = None
    request_headers: dict[str, SecretStr] | None = None

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
        if self.auth is not None and self.request_headers is not None:
            raise ValueError(
                "subagent may define either auth or request_headers, not both."
            )
        return self

    def resolve_agent_card(self, *, base_dir: Path) -> dict[str, Any]:
        """Resolve the subagent card from an inline card, YAML spec, or JSON card file."""
        # TODO: Support remote Agent Card discovery from
        # /.well-known/agent-card.json for subagents configured by URL.
        if self.agent_card is not None:
            card = deepcopy(self.agent_card)
            _validate_a2a_card(card, label="subagent.agent_card")
            return card

        if self.spec_path is not None:
            spec_path = _resolve_path(self.spec_path, base_dir=base_dir)
            return YamlAgentSpec.from_yaml_file(spec_path).advertised_a2a_card()

        assert self.card_path is not None
        card_path = _resolve_path(self.card_path, base_dir=base_dir)
        card = json.loads(card_path.read_text(encoding="utf-8"))
        _validate_a2a_card(card, label=f"subagent.card_path '{card_path}'")
        return card

    def resolve_request_headers(
        self,
        agent_card: dict[str, Any],
    ) -> dict[str, str] | None:
        """Build either card-derived or explicitly configured request headers."""
        if self.auth is not None:
            return self.auth.request_headers(agent_card)
        if self.request_headers is None:
            return None

        headers: dict[str, str] = {}
        for name, value in self.request_headers.items():
            if not name.strip() or "\r" in name or "\n" in name:
                raise ValueError(
                    "subagent request_headers contains an invalid header name."
                )
            header_value = value.get_secret_value()
            if "\r" in header_value or "\n" in header_value:
                raise ValueError(
                    "subagent request_headers contains an invalid header value."
                )
            headers[name] = header_value
        return headers

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
            request_headers=self.resolve_request_headers(agent_card),
        )


class YamlAgentSpec(BaseModel):
    """One YAML file describing one AUTOMA-AI agent, optionally A2A-served."""

    spec_version: Literal["v1"] = "v1"
    agent: AgentIdentitySpec | None = None
    a2a: A2ASpec | None = None
    agent_card: dict[str, Any] | None = None
    instructions: InstructionsSpec
    model: ModelSpec
    runtime: RuntimeSpec = Field(default_factory=RuntimeSpec)
    server: ServerSpec = Field(default_factory=ServerSpec)
    service: ServiceConfig = Field(default_factory=ServiceConfig)

    mcp: MCPConfigSpec | None = None
    subagents: list[SubAgentYamlSpec] = Field(default_factory=list)
    retriever: dict[str, Any] | None = None
    memory: dict[str, Any] | None = None
    skills: dict[str, Any] | None = None
    tools: dict[str, Any] | list[dict[str, Any]] | None = None
    blackboard: dict[str, Any] | None = None
    checkpointer: dict[str, Any] | str | None = None
    budget: dict[str, Any] | None = None
    telemetry: dict[str, Any] | str | None = None
    hooks: dict[str, Any] | None = None

    _base_dir: Path = Path.cwd()

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_identity_and_a2a(self) -> "YamlAgentSpec":
        if self.a2a is not None and self.agent is None:
            raise ValueError("'a2a' requires the new 'agent' section.")
        if (self.agent is None) == (self.agent_card is None):
            raise ValueError("requires exactly one of 'agent' or 'agent_card'.")
        if self.agent_card is not None:
            _validate_a2a_card(self.agent_card, label="agent_card")
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
        data = _resolve_env_placeholders(data)
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
        data = _resolve_env_placeholders(data)
        spec = cls.model_validate(data)
        if base_dir is not None:
            spec._base_dir = Path(base_dir).resolve()
        return spec

    def resolve_instructions(self) -> str:
        """Return the final system instructions passed into ``AgentFactory``."""
        return self.instructions.resolve(base_dir=self._base_dir)

    def runtime_card(self) -> dict[str, Any]:
        """Return the card-shaped runtime metadata required by ``AgentFactory``."""
        if self.agent_card is not None:
            return deepcopy(self.agent_card)

        assert self.agent is not None
        card: dict[str, Any] = {
            "name": self.agent.name,
            "description": self.agent.description,
        }
        if self.agent.version is not None:
            card["version"] = self.agent.version
        return card

    def a2a_card(self) -> dict[str, Any]:
        """Build the public A2A card, or fail when this is a standalone agent."""
        if self.agent_card is not None:
            return deepcopy(self.agent_card)
        if self.a2a is None:
            raise ValueError(
                "A2A server loading requires 'a2a' configuration or a legacy "
                "'agent_card'. Use load_agent_factory_from_yaml() for standalone agents."
            )

        assert self.agent is not None
        card: dict[str, Any] = {
            "name": self.agent.name,
            "description": self.agent.description,
            "version": self.a2a.version or self.agent.version or "0.1.0",
            "defaultInputModes": self.a2a.default_input_modes,
            "defaultOutputModes": self.a2a.default_output_modes,
            "capabilities": deepcopy(self.a2a.capabilities),
            "supportedInterfaces": [
                {
                    "url": self.a2a.url,
                    "protocolBinding": self.a2a.protocol_binding,
                    "protocolVersion": self.a2a.protocol_version,
                }
            ],
        }
        if self.a2a.skills is not None:
            card["skills"] = deepcopy(self.a2a.skills)
        _validate_a2a_card(card, label="a2a")
        return card

    def advertised_a2a_card(self) -> dict[str, Any]:
        """Return the public A2A card exactly as this spec's server advertises it."""
        return normalize_a2a_card_for_server(
            self.a2a_card(),
            base_url_path=self.server.base_url_path,
        )

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
            "card": self.runtime_card(),
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
            "memory_config": _rebase_memory_config(
                self.memory, base_dir=self._base_dir
            ),
            "skills_config": _rebase_skills_config(
                self.skills, base_dir=self._base_dir
            ),
            "tools_config": _rebase_tools_config(self.tools, base_dir=self._base_dir),
            "blackboard_config": _rebase_blackboard_config(
                self.blackboard, base_dir=self._base_dir
            ),
            "checkpointer_config": self.checkpointer,
            "budget_config": _rebase_budget_config(
                self.budget, base_dir=self._base_dir
            ),
            "telemetry_config": _rebase_telemetry_config(
                self.telemetry, base_dir=self._base_dir
            ),
            "hook_config": deepcopy(self.hooks),
            "model_base_url": self.model.base_url,
            "api_key": self.model.api_key,
            "api_version": self.model.api_version,
            "model_max_retries": self.model.max_retries,
            "transient_retry_attempts": self.runtime.transient_retry_attempts,
            "debug": self.runtime.debug,
        }

    def to_agent_factory(self) -> AgentFactory:
        """Build an ``AgentFactory`` from the YAML spec."""
        return AgentFactory(**self.to_factory_kwargs())

    def to_a2a_server(self) -> A2AAgentServer:
        """Build a single ``A2AAgentServer`` from the YAML spec.

        Host, port, and default base path are derived by ``A2AAgentServer`` from
        ``supportedInterfaces[0].url`` on the public A2A card.
        """
        card = self.a2a_card()
        return A2AAgentServer(
            agent_builder=self.to_agent_factory(),
            card=card,
            log_dir=self.server.log_dir,
            base_url_path=self.server.base_url_path,
            health_check_path=self.server.health_check_path,
            service_config=self.service,
        )


YamlAgentSource: TypeAlias = str | Path | YamlAgentSpec


def _resolve_agent_spec(source: YamlAgentSource) -> YamlAgentSpec:
    """Normalize a YAML path or pre-loaded spec into ``YamlAgentSpec``."""
    if isinstance(source, YamlAgentSpec):
        return source
    return YamlAgentSpec.from_yaml_file(source)


def _resolve_path(path: str, *, base_dir: Path) -> Path:
    """Resolve a YAML-authored path string relative to the YAML file directory."""
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = base_dir / resolved
    return resolved


def _resolve_env_placeholders(value: Any, *, path: tuple[str, ...] = ()) -> Any:
    """Resolve ${ENV_NAME} placeholders in secret-like YAML config fields."""
    if isinstance(value, dict):
        return {
            key: _resolve_env_placeholders(item, path=path + (str(key),))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_resolve_env_placeholders(item, path=path) for item in value]
    if not isinstance(value, str):
        return value
    if not _should_resolve_env_placeholders(path):
        return value

    def replace(match: re.Match[str]) -> str:
        env_name = match.group(1)
        if env_name not in os.environ:
            raise ValueError(
                f"Environment variable '{env_name}' is required by YAML agent spec."
            )
        return os.environ[env_name]

    return _ENV_PLACEHOLDER_RE.sub(replace, value)


def _should_resolve_env_placeholders(path: tuple[str, ...]) -> bool:
    """Return true for YAML keys intended to carry secrets or credentials."""
    if not path:
        return False
    if "request_headers" in path:
        return True
    key = path[-1].lower()
    return key in _ENV_PLACEHOLDER_KEY_NAMES or key.endswith(
        _ENV_PLACEHOLDER_KEY_SUFFIXES
    )


def _validate_a2a_card(card: Any, *, label: str) -> None:
    """Validate the minimum A2A 1.0 card shape needed by this loader."""
    if not isinstance(card, dict):
        raise ValueError(f"{label} must be a mapping.")
    if not card.get("name"):
        raise ValueError(f"{label}.name is required.")
    interfaces = card.get("supportedInterfaces")
    if not isinstance(interfaces, list) or not interfaces:
        raise ValueError(
            f"{label}.supportedInterfaces must contain at least one interface."
        )
    primary = interfaces[0]
    if not isinstance(primary, dict):
        raise ValueError(f"{label}.supportedInterfaces[0] must be a mapping.")
    url = primary.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError(f"{label}.supportedInterfaces[0].url is required.")


def _rebase_skills_config(
    skills: dict[str, Any] | None,
    *,
    base_dir: Path,
) -> dict[str, Any] | None:
    """Return a copy of skills config with known path fields made spec-relative.

    `SkillManager` resolves paths against the process working directory, so the
    YAML loader rebases `allowed_roots` and registry entry `path` values before
    passing the config into `AgentFactory`.
    """
    if skills is None:
        return None

    resolved = deepcopy(skills)
    allowed_roots = resolved.get("allowed_roots")
    if isinstance(allowed_roots, list):
        resolved["allowed_roots"] = [
            _rebase_path_string(root, base_dir=base_dir) for root in allowed_roots
        ]

    registry = resolved.get("registry")
    if isinstance(registry, dict):
        for name, entry in registry.items():
            if isinstance(entry, str):
                registry[name] = _rebase_path_string(entry, base_dir=base_dir)
            elif isinstance(entry, dict):
                _rebase_mapping_path(entry, "path", base_dir=base_dir)

    return resolved


def _rebase_tools_config(
    tools: dict[str, Any] | list[dict[str, Any]] | None,
    *,
    base_dir: Path,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    """Return a copy of tools config with known built-in path fields rebased.

    The loader intentionally handles only path fields with known semantics.
    Currently those are `run_python.config.workspace_root`,
    `run_python.config.failure_experience_path`, and `yaml_agent.config.base_dir`;
    arbitrary custom tool strings are left untouched.
    """
    if tools is None:
        return None

    resolved = deepcopy(tools)
    tool_entries = resolved.get("tools") if isinstance(resolved, dict) else resolved
    if not isinstance(tool_entries, list):
        return resolved

    for entry in tool_entries:
        if not isinstance(entry, dict):
            continue
        config = entry.get("config")
        if not isinstance(config, dict):
            continue
        if entry.get("type") == "run_python":
            _rebase_mapping_path(config, "workspace_root", base_dir=base_dir)
            _rebase_mapping_path(config, "failure_experience_path", base_dir=base_dir)
        elif entry.get("type") == "yaml_agent":
            _rebase_mapping_path(config, "base_dir", base_dir=base_dir)

    return resolved


def _rebase_blackboard_config(
    blackboard: dict[str, Any] | None,
    *,
    base_dir: Path,
) -> dict[str, Any] | None:
    """Return a copy of blackboard config with local store directories rebased.

    Local JSON blackboard `base_dir` values are filesystem paths, so relative
    values are interpreted from the YAML file directory rather than the process
    working directory.
    """
    if blackboard is None:
        return None

    resolved = deepcopy(blackboard)
    store = resolved.get("store")
    if isinstance(store, dict):
        _rebase_mapping_path(store, "base_dir", base_dir=base_dir)
    _rebase_mapping_path(resolved, "base_dir", base_dir=base_dir)

    return resolved


def _rebase_budget_config(
    budget: dict[str, Any] | None,
    *,
    base_dir: Path,
) -> dict[str, Any] | None:
    """Return a copy of budget config with local SQLite paths rebased."""
    if budget is None:
        return None

    resolved = deepcopy(budget)
    store = resolved.get("store")
    if isinstance(store, dict) and store.get("backend", "sqlite") == "sqlite":
        _rebase_mapping_path(store, "db_path", base_dir=base_dir)

    return resolved


def _rebase_memory_config(
    memory: dict[str, Any] | None,
    *,
    base_dir: Path,
) -> dict[str, Any] | None:
    """Return a copy of memory config with local store paths rebased."""
    if memory is None:
        return None

    resolved = deepcopy(memory)
    stores = resolved.get("stores")
    if isinstance(stores, list):
        for store in stores:
            if not isinstance(store, dict):
                continue
            store_config = store.get("store_config")
            if isinstance(store_config, dict):
                _rebase_mapping_path(store_config, "db_path", base_dir=base_dir)

    return resolved


def _rebase_telemetry_config(
    telemetry: dict[str, Any] | str | None,
    *,
    base_dir: Path,
) -> dict[str, Any] | str | None:
    """Return telemetry config with local JSONL paths rebased.

    YAML specs are often launched from a different working directory than the
    spec file itself. Rebasing here keeps telemetry output colocated with the
    example/spec unless the user provided an absolute path.
    """
    if telemetry is None or isinstance(telemetry, str):
        return telemetry

    resolved = deepcopy(telemetry)
    _rebase_mapping_path(resolved, "path", base_dir=base_dir)
    return resolved


def _rebase_mapping_path(
    mapping: dict[str, Any],
    key: str,
    *,
    base_dir: Path,
) -> None:
    """Rebase one mapping value in place when the value is a path string."""
    if isinstance(mapping.get(key), str):
        mapping[key] = _rebase_path_string(mapping[key], base_dir=base_dir)


def _rebase_path_string(value: Any, *, base_dir: Path) -> Any:
    """Return a spec-relative absolute-ish path string, preserving non-strings."""
    if not isinstance(value, str):
        return value
    return str(_resolve_path(value, base_dir=base_dir))


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
