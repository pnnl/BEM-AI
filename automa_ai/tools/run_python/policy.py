"""Sandbox policy checks for run_python."""

from __future__ import annotations

import ast

from automa_ai.tools.run_python.config import RunPythonToolConfig


class PolicyViolationError(ValueError):
    """Raised when user code violates sandbox policy."""


_BLOCKED_CALLS = {"__import__", "eval", "exec", "compile"}
_BLOCKED_ATTRS = {
    "execl",
    "execle",
    "execlp",
    "execlpe",
    "execv",
    "execve",
    "execvp",
    "execvpe",
    "system",
    "popen",
    "Popen",
    "posix_spawn",
    "posix_spawnp",
    "run",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "spawnv",
    "spawnve",
    "spawnvp",
    "spawnvpe",
    "call",
    "check_output",
    "check_call",
    "import_module",
}
_ALLOWED_BLOCKED_IMPORT_MODULES = {"urllib.parse"}


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
            _validate_call(node)


def _validate_call(node: ast.Call) -> None:
    if isinstance(node.func, ast.Name) and node.func.id in _BLOCKED_CALLS:
        raise PolicyViolationError(f"Blocked function call: {node.func.id}")

    if isinstance(node.func, ast.Attribute) and node.func.attr in _BLOCKED_ATTRS:
        raise PolicyViolationError(f"Blocked call pattern: *.{node.func.attr}")

    if isinstance(node.func, ast.Name) and node.func.id == "getattr":
        if len(node.args) >= 2:
            second = node.args[1]
            if isinstance(second, ast.Constant) and second.value == "__import__":
                raise PolicyViolationError("Blocked dynamic access to __import__.")


def _validate_import(name: str, blocked: set[str], allowed: set[str]) -> None:
    root = name.split(".", 1)[0]
    if name in _ALLOWED_BLOCKED_IMPORT_MODULES:
        return
    if root in blocked:
        raise PolicyViolationError(f"Blocked import: {root}")
    if allowed and root not in allowed:
        raise PolicyViolationError(
            f"Import '{root}' is not in allowed_imports policy."
        )
