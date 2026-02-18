from __future__ import annotations

import copy
import re
from abc import ABC, abstractmethod
from datetime import timezone, datetime
from typing import Any

from automa_ai.blackboard.errors import RevisionConflictError, DocumentNotFoundError
from automa_ai.blackboard.models import BlackboardDocument, BlackboardPatch, BlackboardEvent
from automa_ai.blackboard.schema import BlackboardSchemaValidator

_PATH_TOKEN_RE = re.compile(r"([^.\[\]]+)|(\[(\d+)\])")


def parse_path(path: str) -> list[str | int]:
    tokens: list[str | int] = []
    for part in path.split("."):
        if not part:
            continue
        idx = 0
        while idx < len(part):
            match = _PATH_TOKEN_RE.match(part, idx)
            if not match:
                raise ValueError(f"Invalid path segment near '{part[idx:]}'.")
            key = match.group(1)
            index = match.group(3)
            if key is not None:
                tokens.append(key)
            elif index is not None:
                tokens.append(int(index))
            idx = match.end()
    return tokens


def _ensure_list_size(target: list[Any], index: int) -> None:
    while len(target) <= index:
        target.append(None)


def _container_for_next(next_token: str | int) -> dict[str, Any] | list[Any]:
    return [] if isinstance(next_token, int) else {}


def _resolve_parent(data: Any, tokens: list[str | int], create_missing: bool) -> tuple[Any, str | int]:
    if not tokens:
        raise ValueError("Path cannot be empty.")
    current = data
    for i, token in enumerate(tokens[:-1]):
        next_token = tokens[i + 1]
        if isinstance(token, str):
            if not isinstance(current, dict):
                raise ValueError(f"Expected object at '{token}'.")
            if token not in current:
                if not create_missing:
                    raise KeyError(token)
                current[token] = _container_for_next(next_token)
            current = current[token]
        else:
            if not isinstance(current, list):
                raise ValueError(f"Expected list for index {token}.")
            _ensure_list_size(current, token)
            if current[token] is None and create_missing:
                current[token] = _container_for_next(next_token)
            current = current[token]
    return current, tokens[-1]


def get_path_value(data: dict[str, Any], path: str | None) -> Any:
    if not path:
        return data
    tokens = parse_path(path)
    current: Any = data
    for token in tokens:
        if isinstance(token, str):
            if not isinstance(current, dict) or token not in current:
                return None
            current = current[token]
        else:
            if not isinstance(current, list) or token >= len(current):
                return None
            current = current[token]
    return current


def _set_path(data: dict[str, Any], path: str, value: Any) -> tuple[Any, Any]:
    tokens = parse_path(path)
    parent, key = _resolve_parent(data, tokens, create_missing=True)
    before = None
    if isinstance(key, str):
        if not isinstance(parent, dict):
            raise ValueError(f"Expected object at path '{path}'.")
        before = copy.deepcopy(parent.get(key))
        parent[key] = value
    else:
        if not isinstance(parent, list):
            raise ValueError(f"Expected list at path '{path}'.")
        _ensure_list_size(parent, key)
        before = copy.deepcopy(parent[key])
        parent[key] = value
    return before, value


def _deep_merge(target: Any, patch: Any) -> Any:
    if isinstance(target, dict) and isinstance(patch, dict):
        merged = copy.deepcopy(target)
        for key, value in patch.items():
            if key in merged:
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged
    return copy.deepcopy(patch)


def _merge_path(data: dict[str, Any], path: str, value: Any) -> tuple[Any, Any]:
    current = get_path_value(data, path)
    merged = _deep_merge(current if current is not None else {}, value)
    before, _ = _set_path(data, path, merged)
    return before, merged


def _append_path(data: dict[str, Any], path: str, value: Any) -> tuple[Any, Any]:
    current = get_path_value(data, path)
    if current is None:
        _set_path(data, path, [])
        current = get_path_value(data, path)
    if not isinstance(current, list):
        raise ValueError(f"Path '{path}' must resolve to a list for append.")
    before = copy.deepcopy(current)
    current.append(value)
    return before, copy.deepcopy(current)


def _remove_path(data: dict[str, Any], path: str) -> tuple[Any, Any]:
    tokens = parse_path(path)
    parent, key = _resolve_parent(data, tokens, create_missing=False)
    if isinstance(key, str):
        if not isinstance(parent, dict):
            raise ValueError(f"Expected object at path '{path}'.")
        before = copy.deepcopy(parent.get(key))
        parent.pop(key, None)
    else:
        if not isinstance(parent, list):
            raise ValueError(f"Expected list at path '{path}'.")
        before = copy.deepcopy(parent[key]) if key < len(parent) else None
        if key < len(parent):
            parent.pop(key)
    return before, None


class BlackboardStore(ABC):
    def __init__(self, validator: BlackboardSchemaValidator):
        self.validator = validator

    @abstractmethod
    def load(self, session_id: str) -> BlackboardDocument:
        raise NotImplementedError

    @abstractmethod
    def create(
        self,
        session_id: str,
        schema_name: str,
        schema_version: str,
        initial_data: dict[str, Any] | None = None,
    ) -> BlackboardDocument:
        raise NotImplementedError

    @abstractmethod
    def save(self, doc: BlackboardDocument, expected_revision: int | None = None) -> BlackboardDocument:
        raise NotImplementedError

    def apply_patch(
        self,
        session_id: str,
        patch: BlackboardPatch,
        expected_revision: int | None = None,
    ) -> BlackboardDocument:
        doc = self.load(session_id)
        if expected_revision is not None and doc.revision != expected_revision:
            raise RevisionConflictError(
                f"Expected revision {expected_revision}, found {doc.revision}."
            )

        data = copy.deepcopy(doc.data)
        events = list(doc.events)
        for op in patch.ops:
            if op.op == "set":
                before, after = _set_path(data, op.path, op.value)
            elif op.op == "merge":
                before, after = _merge_path(data, op.path, op.value or {})
            elif op.op == "append":
                before, after = _append_path(data, op.path, op.value)
            elif op.op == "remove":
                before, after = _remove_path(data, op.path)
            else:  # pragma: no cover
                raise ValueError(f"Unsupported patch op {op.op}.")

            events.append(
                BlackboardEvent(
                    actor=patch.actor,
                    op=op.op,
                    path=op.path,
                    before=before,
                    after=after,
                    note=patch.note,
                )
            )

        self.validator.validate(doc.schema_name, doc.schema_version, data)
        doc.data = data
        doc.events = events
        return self.save(doc, expected_revision=expected_revision)

    def get_or_create(
        self,
        session_id: str,
        schema_name: str,
        schema_version: str,
        initial_data: dict[str, Any] | None = None,
    ) -> BlackboardDocument:
        try:
            return self.load(session_id)
        except DocumentNotFoundError:
            return self.create(session_id, schema_name, schema_version, initial_data)


def bump_revision(doc: BlackboardDocument) -> BlackboardDocument:
    doc.revision += 1
    doc.updated_at = datetime.now(timezone.utc)
    return doc
