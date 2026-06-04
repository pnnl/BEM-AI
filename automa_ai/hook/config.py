from __future__ import annotations

from copy import deepcopy
from importlib import import_module
import logging
from typing import Any

from automa_ai.hook.context import (
    ContextPipeline,
    MemoryContextProvider,
    RetrieverContextProvider,
)
from automa_ai.hook.hooks import HookRunner
from automa_ai.hook.input_assembler import InputAssembler
from automa_ai.hook.turn_input_builder import TurnInputBuilder


def _import_from_path(path: str) -> Any:
    """Import a configured component from a ``module:attribute`` string."""
    if ":" not in path:
        raise ValueError(
            f"Invalid hook impl '{path}'. Expected format 'module:ClassName'."
        )
    module_path, attr = path.split(":", 1)
    module = import_module(module_path)
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise ValueError(
            f"Hook impl '{path}' could not be imported. Missing attribute '{attr}'."
        ) from exc


def _build_component(spec: Any, *, label: str) -> Any:
    """Instantiate one configured hook, context provider, or input assembler."""
    if not isinstance(spec, dict):
        return spec

    impl = spec.get("impl") or spec.get("path")
    if not impl:
        raise ValueError(f"{label} requires 'impl'.")
    config = deepcopy(spec.get("config") or {})
    component_cls = _import_from_path(impl)

    if hasattr(component_cls, "from_config") and callable(
        getattr(component_cls, "from_config")
    ):
        return component_cls.from_config(config)
    return component_cls(**config)


def build_turn_input_builder_from_config(
    config: dict[str, Any] | None,
    *,
    retriever: Any | None = None,
    memory_manager: Any | None = None,
    hook_runner: HookRunner | None = None,
    context_pipeline: ContextPipeline | None = None,
    input_assembler: InputAssembler | None = None,
    logger: logging.Logger | None = None,
    debug: bool = False,
) -> TurnInputBuilder:
    """Build a turn input builder from runtime objects and optional config.

    Direct Python callers can pass concrete ``HookRunner``, ``ContextPipeline``,
    ``InputAssembler``, or ``TurnInputBuilder`` objects. YAML callers pass a
    plain config mapping, so this function bridges that mapping into the same
    runtime objects while preserving the built-in retriever and memory providers
    unless explicitly disabled.
    """

    if config is None:
        return TurnInputBuilder.default(
            retriever=retriever,
            memory_manager=memory_manager,
            hook_runner=hook_runner,
            context_pipeline=context_pipeline,
            input_assembler=input_assembler,
            logger=logger,
            debug=debug,
        )

    resolved = deepcopy(config)
    include_default_context = resolved.get("include_default_context", True)

    if hook_runner is None:
        hook_specs = resolved.get("turn_hooks", resolved.get("hooks", [])) or []
        hook_runner = HookRunner(
            _build_component(spec, label="hooks.turn_hooks[]")
            for spec in hook_specs
        )

    if context_pipeline is None:
        providers = []
        if include_default_context:
            if retriever is not None:
                providers.append(
                    RetrieverContextProvider(
                        retriever,
                        logger=logger,
                        debug=debug,
                    )
                )
            if memory_manager is not None:
                providers.append(
                    MemoryContextProvider(
                        memory_manager,
                        logger=logger,
                        debug=debug,
                    )
                )
        for spec in resolved.get("context_providers", []) or []:
            providers.append(
                _build_component(spec, label="hooks.context_providers[]")
            )
        context_pipeline = ContextPipeline(providers)

    if input_assembler is None:
        assembler_spec = resolved.get("input_assembler")
        input_assembler = (
            _build_component(assembler_spec, label="hooks.input_assembler")
            if assembler_spec is not None
            else InputAssembler()
        )

    return TurnInputBuilder(
        hook_runner=hook_runner,
        context_pipeline=context_pipeline,
        input_assembler=input_assembler,
    )
