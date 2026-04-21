from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from automa_ai.tools.base import BaseDefaultTool, RuntimeDeps
from automa_ai.tools.registry import CUSTOM_TOOL_REGISTRY


def _without_param(fn: Callable, param_name: str) -> Callable:
    """
    Return a wrapper around `fn` whose public signature omits `param_name`.

    The wrapper is NOT meant to be called directly (the hidden param would be
    missing). It exists purely so schema-introspection tools (LangChain,
    Pydantic, etc.) don't see `param_name`.

    Preserves:
      - name, docstring, module
      - async-ness (returns async wrapper for async fn)
      - remaining parameter annotations and defaults
      - return annotation
    """
    sig = inspect.signature(fn)
    if param_name not in sig.parameters:
        raise ValueError(
            f"{fn.__qualname__} has no parameter named {param_name}"
        )

    new_params = [p for name, p in sig.parameters.items() if name != param_name]
    new_sig = sig.replace(parameters=new_params)

    # Build a clean __annotations__ dict (drop the hidden param, keep 'return')
    new_annotations = {
        k: v for k, v in getattr(fn, "__annotations__", {}).items()
        if k != param_name
    }

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            raise RuntimeError(
                f"{fn.__qualname__}: schema-only wrapper called directly; "
                f"parameter {param_name} is injected by the framework."
            )
    else:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            raise RuntimeError(
                f"{fn.__qualname__}: schema-only wrapper called directly; "
                f"parameter {param_name} is injected by the framework."
            )

    wrapper.__signature__ = new_sig
    wrapper.__annotations__ = new_annotations
    return wrapper

def tool(
    func: Callable | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    parse_docstring: bool = True,
    config_schema: type[BaseModel] | None = None,
):
    """
    Register a function as a custom tool. Supports config injection.

    Usage:
        # Simple (no config needed):
        @tool
        def my_tool(text: str, count: int = 1) -> str:
            '''Repeat text.

            Args:
                text: Text to repeat
                count: Number of times
            '''
            return text * count

        # With config:
        class MyConfig(BaseModel):
            api_key: str

        @tool(config_schema=MyConfig)
        def my_tool(query: str, *, config: MyConfig) -> dict:
            '''Search with API.

            Args:
                query: Search query
            '''
            return {"results": search(query, config.api_key)}

    Args:
        func: Function to convert to a tool
        name: Optional display name shown to the LLM. Does NOT affect how the
              tool is referenced in configuration — tools are always registered
              and looked up by their fully qualified name (`module.function`).
        description: Optional description override
        parse_docstring: Whether to parse Google-style docstrings
        config_schema: Optional Pydantic model for configuration validation

    Returns:
        The original function (unmodified)
    """
    def decorator(fn: Callable) -> Callable:
        sig = inspect.signature(fn)
        is_async = inspect.iscoroutinefunction(fn)

        has_config_schema = config_schema is not None
        has_config_param = "config" in sig.parameters

        # Validate config_schema and config parameter match
        if has_config_schema != has_config_param:
            if has_config_schema:
                raise TypeError(
                    f"{fn.__qualname__}: config_schema provided but function has "
                    f"no 'config' parameter"
                )
            else:
                raise TypeError(
                    f"{fn.__qualname__}: function declares a 'config' parameter but "
                    f"no config_schema was provided to @tool"
                )
            
        # Hide 'config' from LLM schema if present
        schema_fn = _without_param(fn, "config") if has_config_param else fn

        tool_name = name or fn.__name__

        # Create LangChain tool using StructuredTool.from_function
        langchain_tool = StructuredTool.from_function(
            func=None if is_async else schema_fn,
            coroutine=schema_fn if is_async else None,
            name=tool_name,
            description=description,
            parse_docstring=parse_docstring,
            infer_schema=True,
        )

        fq_name = f"{fn.__module__}.{fn.__name__}"

        class Wrapper(BaseDefaultTool):
            type: str = fq_name
            name: str = tool_name

            def __init__(self, config: dict, runtime_deps: RuntimeDeps):
                self._config = config
                self._runtime_deps = runtime_deps
                self._langchain_tool = langchain_tool

                if config_schema:
                    self._validated_config = config_schema.model_validate(config)
                else:
                    self._validated_config = None

            @property
            def args_schema(self) -> type[BaseModel]:
                return self._langchain_tool.args_schema

            @property
            def description(self) -> str:
                return self._langchain_tool.description

            async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
                # If function needs config, inject it and call directly
                if has_config_param:
                    validated = self._langchain_tool.args_schema.model_validate(payload)
                    kwargs = {**validated.model_dump(), "config": self._validated_config}
                    result = await fn(**kwargs) if is_async else fn(**kwargs)
                else:
                    # Use LangChain's tool execution (handles sync/async)
                    result = await self._langchain_tool.ainvoke(payload)

                # Normalize to dict
                if isinstance(result, BaseModel):
                    return result.model_dump(mode="json")
                if not isinstance(result, dict):
                    return {"result": result}
                return result
            
        # Register builder
        def builder(config: dict[str, Any], runtime_deps: RuntimeDeps) -> BaseDefaultTool:
            return Wrapper(config, runtime_deps)


        CUSTOM_TOOL_REGISTRY.register(fq_name, builder)

        setattr(fn, "__tool_name__", tool_name)

        return fn

    # Support both @tool and @tool(...)
    if func is not None:
        return decorator(func)
    return decorator