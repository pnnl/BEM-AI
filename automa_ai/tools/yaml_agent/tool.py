"""YAML agent execution default tool."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from automa_ai.agents.remote_agent import (
    StreamEvent,
    get_subagent_context_id,
    get_subagent_emitter,
)
from automa_ai.tools.base import BaseDefaultTool


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
        if path.is_absolute():
            return path
        if self.config.base_dir:
            return Path(self.config.base_dir) / path
        return path

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
        from automa_ai.config.agent_spec import load_agent_factory_from_yaml

        args = YamlAgentInput.model_validate(payload)
        yaml_path = self._resolve_yaml_path(args.yaml_path)
        factory = load_agent_factory_from_yaml(yaml_path)
        agent = factory()
        context_id = args.context_id or get_subagent_context_id() or f"yaml-agent-{uuid4()}"
        task_id = args.task_id or f"yaml-agent-task-{uuid4()}"
        chunks: list[str] = []
        final: str = ""
        requires_user_input = False

        try:
            async for item in agent.stream(
                args.query,
                context_id,
                task_id,
                user_id=args.user_id,
                metadata=args.metadata,
            ):
                content = str(item.get("content", ""))
                is_final = bool(item.get("is_task_complete"))
                requires_user_input = bool(item.get("require_user_input"))

                if content:
                    chunks.append(content)
                    await self._emit_chunk(
                        source=f"yaml_agent:{agent.agent_name}",
                        content=content,
                        yaml_path=yaml_path,
                        final=is_final or requires_user_input,
                    )

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
