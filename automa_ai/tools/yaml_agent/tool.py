"""YAML agent execution default tool."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterable
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from automa_ai.agents.remote_agent import (
    StreamEvent,
    get_subagent_context_id,
    get_subagent_emitter,
)
from automa_ai.tools.base import BaseDefaultTool, content_to_safe_text

ALLOWED_HEADLESS_BUILTIN_TOOL_TYPES = {"web_search", "run_python"}
YAML_SUFFIXES = {".yaml", ".yml"}


class YamlAgentToolConfig(BaseModel):
    """Configuration for the YAML agent execution tool."""

    base_dir: str | None = Field(
        default=None,
        description="Optional base directory used to resolve relative YAML paths.",
    )


class YamlAgentInput(BaseModel):
    yaml_path: str = Field(description="Path to the YAML agent spec.")
    query: str = Field(min_length=1, description="User query to execute.")
    context_id: str | None = Field(
        default=None,
        description="Optional context/session id. Defaults to the active parent context.",
    )
    task_id: str | None = Field(default=None, description="Optional task id.")
    user_id: str | None = Field(default=None, description="Optional user id.")
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional metadata passed to the YAML-defined agent.",
    )


class YamlAgentTool(BaseDefaultTool):
    type = "yaml_agent"

    def __init__(self, config: YamlAgentToolConfig):
        self.config = config

    @property
    def args_schema(self) -> type[BaseModel]:
        return YamlAgentInput

    @property
    def description(self) -> str:
        return (
            "Create an AUTOMA-AI agent from a YAML spec and execute a query. "
            "Streams intermediate chunks to the parent agent when available."
        )

    def _resolve_yaml_path(self, yaml_path: str) -> Path:
        path = Path(yaml_path)
        if self.config.base_dir:
            base_dir = Path(self.config.base_dir).resolve()
            if path.is_absolute():
                resolved = path.resolve()
            else:
                resolved = (base_dir / path).resolve()
            if resolved != base_dir and base_dir not in resolved.parents:
                raise ValueError(
                    "yaml_path must resolve inside yaml_agent.config.base_dir."
                )
            return self._validate_yaml_file_path(resolved)
        if path.is_absolute():
            return self._validate_yaml_file_path(path.resolve())
        return self._validate_yaml_file_path(path)

    @staticmethod
    def _validate_yaml_file_path(path: Path) -> Path:
        if path.suffix.lower() not in YAML_SUFFIXES:
            raise ValueError(f"yaml_path must point to a .yaml or .yml file: {path}")
        if not path.is_file():
            raise ValueError(f"yaml_path must point to an existing YAML file: {path}")
        return path

    @staticmethod
    def _validate_headless_spec(spec: Any, *, yaml_path: Path) -> None:
        """Enforce the bounded headless-subagent contract before agent creation."""
        if spec.mcp is not None:
            raise ValueError(f"Headless YAML subagent cannot define mcp: {yaml_path}")
        if spec.memory is not None:
            raise ValueError(f"Headless YAML subagent cannot define memory: {yaml_path}")
        if spec.checkpointer is not None:
            raise ValueError(
                f"Headless YAML subagent cannot define checkpointer: {yaml_path}"
            )
        if spec.subagents:
            raise ValueError(
                f"Headless YAML subagent cannot define nested subagents: {yaml_path}"
            )

        tools = spec.tools
        if tools is None:
            return
        if isinstance(tools, dict):
            if "tools" not in tools:
                raise ValueError(
                    f"Headless YAML subagent tools mapping must contain a tools list: {yaml_path}"
                )
            tool_entries = tools["tools"]
        else:
            tool_entries = tools
        if not isinstance(tool_entries, list):
            raise ValueError(
                f"Headless YAML subagent tools must be a list or tools mapping: {yaml_path}"
            )

        for entry in tool_entries:
            if not isinstance(entry, dict):
                raise ValueError(
                    f"Headless YAML subagent tool entries must be mappings: {yaml_path}"
                )
            tool_type = entry.get("type")
            if tool_type == "yaml_agent":
                raise ValueError(
                    f"Headless YAML subagent cannot enable yaml_agent: {yaml_path}"
                )
            if tool_type not in ALLOWED_HEADLESS_BUILTIN_TOOL_TYPES and (
                not isinstance(tool_type, str) or "." not in tool_type
            ):
                raise ValueError(
                    "Headless YAML subagent can only enable built-in tools "
                    f"{sorted(ALLOWED_HEADLESS_BUILTIN_TOOL_TYPES)} or custom "
                    f"dotted-path tools; got {tool_type!r}: {yaml_path}"
                )

    async def _emit_chunk(
        self,
        *,
        source: str,
        content: str,
        yaml_path: Path,
        final: bool = False,
    ) -> None:
        emitter = get_subagent_emitter()
        if emitter is None:
            return
        await emitter(
            StreamEvent(
                source=source,
                type="yaml_agent_chunk",
                content=content,
                metadata={"yaml_path": str(yaml_path), "final": final},
            )
        )

    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        from automa_ai.config.agent_spec import (
            YamlAgentSpec,
            load_agent_factory_from_yaml,
        )

        args = YamlAgentInput.model_validate(payload)
        yaml_path = self._resolve_yaml_path(args.yaml_path)
        spec = YamlAgentSpec.from_yaml_file(yaml_path)
        self._validate_headless_spec(spec, yaml_path=yaml_path)
        factory = load_agent_factory_from_yaml(spec)
        agent = factory()
        context_id = (
            args.context_id or get_subagent_context_id() or f"yaml-agent-{uuid4()}"
        )
        task_id = args.task_id or f"yaml-agent-task-{uuid4()}"
        chunks: list[str] = []
        final: str = ""
        requires_user_input = False

        try:
            stream_result = agent.stream(
                args.query,
                context_id,
                task_id,
                user_id=args.user_id,
                metadata=args.metadata,
            )
            if inspect.isawaitable(stream_result):
                stream_result = await stream_result
            if not isinstance(stream_result, AsyncIterable):
                raise TypeError(
                    "agent.stream(...) must return an async iterable of stream items."
                )

            # This is a final text-size guard. Binary payloads are removed
            # structurally by content_to_safe_text before reaching this point.
            _MAX_CHUNK_CHARS = 16_000

            def bounded(content: str) -> str:
                if len(content) <= _MAX_CHUNK_CHARS:
                    return content
                return content[:200] + f"... [truncated {len(content)} chars]"

            async for item in stream_result:
                content = bounded(content_to_safe_text(item.get("content", "")))
                is_final = bool(item.get("is_task_complete"))
                requires_user_input = bool(item.get("require_user_input"))

                if content:
                    await self._emit_chunk(
                        source=f"yaml_agent:{agent.agent_name}",
                        content=content,
                        yaml_path=yaml_path,
                        final=is_final or requires_user_input,
                    )
                    chunks.append(content)

                if is_final or requires_user_input:
                    final = content
                    break

            if not final and chunks:
                final = chunks[-1]

            return {
                "final": final,
                "chunks": chunks,
                "context_id": context_id,
                "task_id": task_id,
                "requires_user_input": requires_user_input,
            }
        finally:
            close_fn = getattr(agent, "close", None)
            if callable(close_fn):
                result = close_fn()
                if inspect.isawaitable(result):
                    await result


def build_yaml_agent_tool(
    config: dict[str, Any],
    _runtime_deps: Any,
) -> YamlAgentTool:
    return YamlAgentTool(YamlAgentToolConfig.model_validate(config))
