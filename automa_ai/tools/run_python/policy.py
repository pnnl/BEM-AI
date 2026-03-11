"""Sandbox policy checks for run_python."""

from __future__ import annotations

import ast

from automa_ai.tools.run_python.config import RunPythonToolConfig


class PolicyViolationError(ValueError):
    """Raised when user code violates sandbox policy."""


_BLOCKED_CALLS = {"__import__", "eval", "exec", "compile"}
_BLOCKED_ATTRS = {"system", "popen", "Popen", "run", "call", "check_output", "check_call"}
_BLOCKED_BASES = {"os", "subprocess"}


def validate_code_policy(code: str, config: RunPythonToolConfig) -> None:
    """Validate Python code against lightweight static policy checks."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise PolicyViolationError(f"Invalid Python syntax: {exc}") from exc

    blocked_imports = set(config.blocked_imports)
    if not config.allow_network:
        blocked_imports.update({"http", "httpx", "aiohttp", "ftplib", "ssl", "websocket"})
    allowed_imports = set(config.allowed_imports)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _validate_import(alias.name, blocked_imports, allowed_imports)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                _validate_import(node.module, blocked_imports, allowed_imports)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _BLOCKED_CALLS:
                raise PolicyViolationError(f"Blocked function call: {node.func.id}")
            if isinstance(node.func, ast.Attribute):
                if (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id in _BLOCKED_BASES
                    and node.func.attr in _BLOCKED_ATTRS
                ):
                    raise PolicyViolationError(
                        f"Blocked call pattern: {node.func.value.id}.{node.func.attr}"
                    )


def _validate_import(name: str, blocked: set[str], allowed: set[str]) -> None:
    root = name.split(".", 1)[0]
    if root in blocked:
        raise PolicyViolationError(f"Blocked import: {root}")
    if allowed and root not in allowed:
        raise PolicyViolationError(
            f"Import '{root}' is not in allowed_imports policy."
        )
