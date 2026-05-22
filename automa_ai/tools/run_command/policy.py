"""Policy validation for curated run_command execution."""

from __future__ import annotations

from pathlib import Path

from automa_ai.tools.run_command.config import RunCommandToolConfig


class CommandPolicyViolationError(ValueError):
    """Raised when argv violates the configured run_command policy."""


def validate_command_policy(argv: list[str], config: RunCommandToolConfig) -> list[str]:
    """Validate argv for the configured profile and return normalized argv."""
    if config.profile != "exploration":
        raise CommandPolicyViolationError(
            f"Unsupported run_command profile: {config.profile}"
        )
    if not argv:
        raise CommandPolicyViolationError("argv must contain at least one item.")
    if any(not isinstance(part, str) or not part for part in argv):
        raise CommandPolicyViolationError("argv must contain only non-empty strings.")

    workspace_root = Path(config.workspace_root).resolve()
    command = argv[0]

    if command == "pwd":
        _require_exact_argv(argv, ["pwd"])
    elif command == "ls":
        _validate_ls(argv, workspace_root, config)
    elif command == "cat":
        _validate_path_only_command(argv, workspace_root, config, min_paths=1)
    elif command in {"head", "tail"}:
        _validate_head_or_tail(argv, workspace_root, config)
    elif command == "sed":
        _validate_sed(argv, workspace_root, config)
    elif command == "rg":
        _validate_rg(argv, workspace_root, config)
    elif command == "git":
        _validate_git(argv)
    else:
        raise CommandPolicyViolationError(
            f"Command is not allowed in exploration profile: {command}"
        )

    if command == "rg":
        return _append_rg_blocked_file_excludes(argv, config)
    return argv


def _require_exact_argv(argv: list[str], expected: list[str]) -> None:
    if argv != expected:
        raise CommandPolicyViolationError(
            f"Only {' '.join(expected)} is allowed in exploration profile."
        )


def _validate_ls(
    argv: list[str],
    workspace_root: Path,
    config: RunCommandToolConfig,
) -> None:
    allowed_flags = {"-1", "-a", "-l", "-la", "-al"}
    paths: list[str] = []
    for arg in argv[1:]:
        if arg.startswith("-"):
            if arg not in allowed_flags:
                raise CommandPolicyViolationError(f"Unsupported ls flag: {arg}")
            continue
        paths.append(arg)
    for path in paths:
        _validate_workspace_path(path, workspace_root, config)


def _validate_path_only_command(
    argv: list[str],
    workspace_root: Path,
    config: RunCommandToolConfig,
    *,
    min_paths: int,
) -> None:
    paths = argv[1:]
    if len(paths) < min_paths:
        raise CommandPolicyViolationError(f"{argv[0]} requires at least one path.")
    for path in paths:
        if path.startswith("-"):
            raise CommandPolicyViolationError(f"Unsupported {argv[0]} argument: {path}")
        _validate_workspace_path(path, workspace_root, config)


def _validate_head_or_tail(
    argv: list[str],
    workspace_root: Path,
    config: RunCommandToolConfig,
) -> None:
    index = 1
    if len(argv) >= 3 and argv[1] == "-n":
        _validate_positive_int(argv[2], option="-n")
        index = 3
    elif len(argv) >= 2 and argv[1].startswith("-"):
        raise CommandPolicyViolationError(f"Unsupported {argv[0]} flag: {argv[1]}")

    paths = argv[index:]
    if not paths:
        raise CommandPolicyViolationError(f"{argv[0]} requires at least one path.")
    for path in paths:
        _validate_workspace_path(path, workspace_root, config)


def _validate_sed(
    argv: list[str],
    workspace_root: Path,
    config: RunCommandToolConfig,
) -> None:
    if len(argv) != 4 or argv[1] != "-n":
        raise CommandPolicyViolationError(
            "Only `sed -n <start>,<end>p <path>` is allowed."
        )
    expr = argv[2]
    if not _is_line_range_expr(expr):
        raise CommandPolicyViolationError(
            "sed expression must use the form `<start>,<end>p`."
        )
    _validate_workspace_path(argv[3], workspace_root, config)


def _validate_rg(
    argv: list[str],
    workspace_root: Path,
    config: RunCommandToolConfig,
) -> None:
    if len(argv) == 1:
        raise CommandPolicyViolationError("rg requires arguments.")

    allowed_flags = {"-n", "--line-number", "-i", "--ignore-case", "-S", "--smart-case"}
    index = 1
    paths: list[str] = []

    if argv[1] == "--files":
        index = 2
        while index < len(argv):
            arg = argv[index]
            if arg in {"-g", "--glob"}:
                index += 1
                if index >= len(argv):
                    raise CommandPolicyViolationError(f"{arg} requires a glob value.")
                _validate_glob(argv[index], config)
            elif arg.startswith("-"):
                raise CommandPolicyViolationError(f"Unsupported rg flag: {arg}")
            else:
                paths.append(arg)
            index += 1
        for path in paths:
            _validate_workspace_path(path, workspace_root, config)
        return

    while index < len(argv) and argv[index].startswith("-"):
        arg = argv[index]
        if arg in allowed_flags:
            index += 1
            continue
        if arg in {"-g", "--glob"}:
            index += 1
            if index >= len(argv):
                raise CommandPolicyViolationError(f"{arg} requires a glob value.")
            _validate_glob(argv[index], config)
            index += 1
            continue
        if arg == "--max-count":
            index += 1
            if index >= len(argv):
                raise CommandPolicyViolationError("--max-count requires a value.")
            _validate_positive_int(argv[index], option="--max-count")
            index += 1
            continue
        raise CommandPolicyViolationError(f"Unsupported rg flag: {arg}")

    if index >= len(argv):
        raise CommandPolicyViolationError("rg requires a search pattern.")
    index += 1  # Search pattern.

    for path in argv[index:]:
        if path.startswith("-"):
            raise CommandPolicyViolationError(f"Unsupported rg argument: {path}")
        paths.append(path)
    for path in paths:
        _validate_workspace_path(path, workspace_root, config)


def _validate_git(argv: list[str]) -> None:
    allowed = {
        ("git", "status"),
        ("git", "status", "--short"),
        ("git", "diff", "--stat"),
        ("git", "diff", "--name-only"),
    }
    if tuple(argv) not in allowed:
        raise CommandPolicyViolationError(
            "Only `git status`, `git status --short`, `git diff --stat`, "
            "and `git diff --name-only` are allowed."
        )


def _validate_workspace_path(
    raw_path: str,
    workspace_root: Path,
    config: RunCommandToolConfig,
) -> None:
    path = Path(raw_path)
    resolved = (
        path.resolve() if path.is_absolute() else (workspace_root / path).resolve()
    )
    if resolved != workspace_root and workspace_root not in resolved.parents:
        raise CommandPolicyViolationError(
            f"Path must stay within workspace_root: {raw_path}"
        )
    relative = resolved.relative_to(workspace_root)
    # Block by path component so nested sensitive files such as nested/.env fail.
    if _contains_blocked_file_name(relative, config.blocked_file_names):
        raise CommandPolicyViolationError(f"Path is blocked by policy: {raw_path}")


def _validate_glob(glob: str, config: RunCommandToolConfig) -> None:
    if not glob or "\x00" in glob:
        raise CommandPolicyViolationError("rg glob must be a non-empty string.")
    normalized = glob.lstrip("!")
    # Reject any glob that explicitly targets a blocked file name, including
    # exclusion globs such as `!.env`; broader matches are still handled by the
    # appended rg excludes below.
    if _glob_targets_blocked_file_name(normalized, config.blocked_file_names):
        raise CommandPolicyViolationError(f"Glob is blocked by policy: {glob}")


def _contains_blocked_file_name(path: Path, blocked_file_names: list[str]) -> bool:
    """Return true when any path component is an exact blocked file name."""
    return any(part in blocked_file_names for part in path.parts)


def _glob_targets_blocked_file_name(glob: str, blocked_file_names: list[str]) -> bool:
    """Return true for globs that explicitly name a blocked file."""
    parts = Path(glob).parts
    return any(part in blocked_file_names for part in parts)


def _append_rg_blocked_file_excludes(
    argv: list[str],
    config: RunCommandToolConfig,
) -> list[str]:
    if not config.blocked_file_names:
        return argv

    insert_at = _rg_blocked_exclude_insert_index(argv)
    excludes: list[str] = []
    for name in config.blocked_file_names:
        # ripgrep applies later globs last, so append excludes after user globs.
        excludes.extend(["-g", f"!{name}", "-g", f"!**/{name}"])
    return [*argv[:insert_at], *excludes, *argv[insert_at:]]


def _rg_blocked_exclude_insert_index(argv: list[str]) -> int:
    """Find the position after rg option tokens and before pattern/path tokens."""
    if len(argv) >= 2 and argv[1] == "--files":
        index = 2
        while index < len(argv):
            arg = argv[index]
            if arg in {"-g", "--glob"}:
                index += 2
            elif arg.startswith("-"):
                index += 1
            else:
                break
        return index

    index = 1
    while index < len(argv) and argv[index].startswith("-"):
        arg = argv[index]
        if arg in {"-g", "--glob", "--max-count"}:
            index += 2
        else:
            index += 1
    return index


def _validate_positive_int(value: str, *, option: str) -> None:
    if not value.isdigit() or int(value) <= 0:
        raise CommandPolicyViolationError(f"{option} requires a positive integer.")


def _is_line_range_expr(expr: str) -> bool:
    """Accept only sed print ranges, for example 10,20p."""
    if not expr.endswith("p"):
        return False
    body = expr[:-1]
    parts = body.split(",")
    return len(parts) == 2 and all(part.isdigit() and int(part) > 0 for part in parts)
