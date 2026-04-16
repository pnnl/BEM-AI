from __future__ import annotations

import copy
import re
from abc import ABC, abstractmethod
from datetime import timezone, datetime
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from automa_ai.blackboard.errors import RevisionConflictError, DocumentNotFoundError
from automa_ai.blackboard.models import BlackboardDocument, BlackboardPatch, BlackboardEvent, BlackboardBackend
from automa_ai.blackboard.schema import BlackboardSchemaValidator

if TYPE_CHECKING:
    from automa_ai.config.blackboard import BlackboardConfig

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

class BlackboardStoreConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    backend: BlackboardBackend | str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BlackboardStoreConfig":
        return cls.model_validate(data)


class BlackboardStoreRegistry:
    """Registry for blackboard store backends."""
    _stores: dict[str, type["BlackboardStore"]] = {}

    @classmethod
    def register(cls, backend: str | BlackboardBackend, store_cls: type["BlackboardStore"]):
        """Register a blackboard store backend.

        Args:
            backend: Backend identifier (enum value or string)
            store_cls: Store class to register

        Raises:
            TypeError: If store_cls is not a subclass of BlackboardStore
        """
        if not isinstance(store_cls, type):
            raise TypeError(f"store_cls must be a class, not {type(store_cls)}")
        if not issubclass(store_cls, BlackboardStore):
            raise TypeError(
                f"store_cls must be a subclass of BlackboardStore, not {store_cls!r}"
            )

        backend_key = backend.value if isinstance(backend, BlackboardBackend) else backend
        cls._stores[backend_key] = store_cls

    @classmethod
    def get(cls, backend: str | BlackboardBackend) -> type["BlackboardStore"]:
        """Get a registered store class by backend identifier.

        Args:
            backend: Backend identifier (enum value or string)

        Returns:
            Store class

        Raises:
            KeyError: If backend is not registered
        """
        from automa_ai.blackboard.errors import BackendNotConfiguredError

        backend_key = backend.value if isinstance(backend, BlackboardBackend) else backend
        if backend_key not in cls._stores:
            raise BackendNotConfiguredError(f"Unknown blackboard backend: {backend_key}")
        return cls._stores[backend_key]


class BlackboardStore(ABC):
    _config_class: type[BlackboardStoreConfig]

    def __init__(self, config: BlackboardStoreConfig | "BlackboardConfig"):
        """Initialize the blackboard store.

        Args:
            config: BlackboardStoreConfig or BlackboardConfig (for backward compatibility)

        Raises:
            ValueError: If config is invalid
        """
        # Import here to avoid circular dependency
        from automa_ai.config.blackboard import BlackboardConfig

        # Handle BlackboardConfig (backward compatibility)
        if isinstance(config, BlackboardConfig):
            if config.store is None:
                raise ValueError("BlackboardConfig.store must be set")
            store_config = config.store
            config = store_config

        if isinstance(config, dict):
            if not hasattr(self.__class__, "_config_class") or self.__class__._config_class is None:
                raise AttributeError(
                    f"{self.__class__.__name__} must define a '_config_class' attribute"
                )
            config = self.__class__._config_class.model_validate(config)

        self.backend = config.backend
        self.validator = BlackboardSchemaValidator()

    @classmethod
    def from_config(cls, config: dict | BlackboardStoreConfig):
        if hasattr(cls, "_config_class") and cls._config_class is not None:
            config = cls._config_class.model_validate(
                config if isinstance(config, dict) else config.model_dump()
            )

        return cls(config)

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


def create_blackboard_store(store_config: dict | BlackboardStoreConfig) -> BlackboardStore:
    """Create a blackboard store instance from configuration.

    Args:
        store_config: Configuration for the blackboard store (dict or BlackboardStoreConfig)

    Returns:
        BlackboardStore: Configured blackboard store instance

    Raises:
        BackendNotConfiguredError: If the specified backend is not supported
        ValueError: If backend is not specified in config
    """
    _ensure_builtin_backends_registered()

    # Extract backend identifier
    if isinstance(store_config, dict):
        backend = store_config.get("backend")
        if not backend:
            raise ValueError("Backend must be specified in store config")
    else:
        backend = store_config.backend

    # Get store class from registry and create instance
    store_cls = BlackboardStoreRegistry.get(backend)
    return store_cls.from_config(store_config)


def _ensure_builtin_backends_registered():
    """Ensure built-in backends are registered on first use."""
    if not BlackboardStoreRegistry._stores:
        # Import and register built-in backends
        from automa_ai.blackboard.backends.local_json import LocalJSONBlackboardStore
        from automa_ai.blackboard.backends.s3_json import S3JSONBlackboardStore
        from automa_ai.blackboard.backends.dynamodb_json import DynamoDBJSONBlackboardStore

        BlackboardStoreRegistry.register(BlackboardBackend.LOCAL_JSON, LocalJSONBlackboardStore)
        BlackboardStoreRegistry.register(BlackboardBackend.S3_JSON, S3JSONBlackboardStore)
        BlackboardStoreRegistry.register(BlackboardBackend.DYNAMODB_JSON, DynamoDBJSONBlackboardStore)
