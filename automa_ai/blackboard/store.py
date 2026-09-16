from __future__ import annotations

import copy
import re
from abc import ABC, abstractmethod
from datetime import timedelta, timezone, datetime
from collections.abc import Mapping
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from automa_ai.blackboard.errors import (
    ApprovalArtifactChangedError,
    ApprovalNotFoundError,
    DocumentNotFoundError,
    InvalidApprovalTransitionError,
    RevisionConflictError,
)
from automa_ai.blackboard.models import (
    ApprovalRecord,
    ApprovalStatus,
    BlackboardBackend,
    BlackboardDocument,
    BlackboardEvent,
    BlackboardPatch,
)
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


def _resolve_parent(
    data: Any, tokens: list[str | int], create_missing: bool
) -> tuple[Any, str | int]:
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


def has_path(data: dict[str, Any], path: str) -> bool:
    """Return whether a path exists, distinguishing a stored null from absence."""
    tokens = parse_path(path)
    if not tokens:
        return False
    current: Any = data
    for token in tokens:
        if isinstance(token, str):
            if not isinstance(current, dict) or token not in current:
                return False
            current = current[token]
        else:
            if not isinstance(current, list) or token >= len(current):
                return False
            current = current[token]
    return True


def _same_artifact_value(left: Any, right: Any) -> bool:
    """Compare JSON-like artifacts without Python's bool/int equivalence.

    Approval snapshots are persisted JSON values. Requiring exact scalar types
    makes a change such as ``true`` to ``1`` visible even inside nested lists or
    objects.
    """
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping):
        return set(left) == set(right) and all(
            _same_artifact_value(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _same_artifact_value(old, new) for old, new in zip(left, right)
        )
    return left == right


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
    def register(
        cls, backend: str | BlackboardBackend, store_cls: type["BlackboardStore"]
    ):
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

        backend_key = (
            backend.value if isinstance(backend, BlackboardBackend) else backend
        )
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

        backend_key = (
            backend.value if isinstance(backend, BlackboardBackend) else backend
        )
        if backend_key not in cls._stores:
            raise BackendNotConfiguredError(
                f"Unknown blackboard backend: {backend_key}"
            )
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
            if (
                not hasattr(self.__class__, "_config_class")
                or self.__class__._config_class is None
            ):
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
    def save(
        self, doc: BlackboardDocument, expected_revision: int | None = None
    ) -> BlackboardDocument:
        """Persist a document, atomically enforcing expected_revision when given.

        Backends that support concurrent writers must implement this comparison
        at their storage boundary (for example, with a conditional update).
        """
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

    def propose_approval(
        self,
        session_id: str,
        artifact_path: str,
        *,
        actor: str | None = None,
        title: str | None = None,
        note: str | None = None,
        expiry_seconds: int | None = None,
        expected_revision: int,
    ) -> BlackboardDocument:
        """Create a pending approval for an existing artifact path."""
        doc = self.load(session_id)
        self._require_revision(doc, expected_revision)
        if not has_path(doc.data, artifact_path):
            raise ValueError(
                f"Approval artifact path does not exist: {artifact_path!r}."
            )
        expires_at = None
        if expiry_seconds is not None:
            if expiry_seconds <= 0:
                raise ValueError("expiry_seconds must be positive when provided.")
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expiry_seconds)
        approval = ApprovalRecord(
            artifact_path=artifact_path,
            artifact_revision=doc.revision,
            # Snapshot the proposed value so unrelated writes do not invalidate
            # review, while edits to the reviewed artifact do.
            artifact_snapshot=copy.deepcopy(get_path_value(doc.data, artifact_path)),
            artifact_snapshot_available=True,
            title=title,
            requested_by=actor,
            request_note=note,
            expires_at=expires_at,
        )
        doc.approvals.append(approval)
        doc.events.append(
            BlackboardEvent(
                actor=actor,
                op="approval.proposed",
                path=artifact_path,
                after=approval.model_dump(mode="json"),
                note=note,
            )
        )
        return self.save(doc, expected_revision=expected_revision)

    def get_approval(self, session_id: str, approval_id: str) -> ApprovalRecord:
        """Return one durable approval record by identifier."""
        doc = self.load(session_id)
        for approval in doc.approvals:
            if approval.approval_id == approval_id:
                return approval
        raise ApprovalNotFoundError(f"Approval {approval_id!r} was not found.")

    def list_approvals(
        self,
        session_id: str,
        *,
        status: ApprovalStatus | str | None = None,
    ) -> list[ApprovalRecord]:
        """List durable approval records, optionally filtered by status."""
        approvals = self.load(session_id).approvals
        if status is None:
            return list(approvals)
        resolved_status = ApprovalStatus(status)
        return [item for item in approvals if item.status is resolved_status]

    def resolve_approval(
        self,
        session_id: str,
        approval_id: str,
        decision: ApprovalStatus | str,
        *,
        reviewer: str,
        note: str | None = None,
        expected_revision: int,
    ) -> BlackboardDocument:
        """Apply the human-only approved or rejected decision to a pending record."""
        status = ApprovalStatus(decision)
        if status not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
            raise ValueError("decision must be 'approved' or 'rejected'.")
        doc = self.load(session_id)
        self._require_revision(doc, expected_revision)
        approval = self._find_approval(doc, approval_id)
        if approval.status is not ApprovalStatus.PENDING:
            raise InvalidApprovalTransitionError(
                f"Cannot resolve approval in state {approval.status.value!r}."
            )
        self._assert_approval_actionable(doc, approval)
        approval.status = status
        approval.reviewer = reviewer
        approval.reviewed_at = datetime.now(timezone.utc)
        approval.review_note = note
        doc.events.append(
            BlackboardEvent(
                actor=reviewer,
                op=f"approval.{status.value}",
                path=approval.artifact_path,
                after=approval.model_dump(mode="json"),
                note=note,
            )
        )
        return self.save(doc, expected_revision=expected_revision)

    def claim_approved_resume(
        self,
        session_id: str,
        approval_id: str,
        *,
        actor: str | None = None,
        allow_one_time_resume: bool = True,
        expected_revision: int,
    ) -> BlackboardDocument:
        """Consume an approved checkpoint before a workflow continuation."""
        doc = self.load(session_id)
        self._require_revision(doc, expected_revision)
        approval = self._find_approval(doc, approval_id)
        if approval.status is not ApprovalStatus.APPROVED:
            raise InvalidApprovalTransitionError(
                f"Cannot resume approval in state {approval.status.value!r}."
            )
        self._assert_approval_actionable(doc, approval)
        if allow_one_time_resume:
            # A reusable checkpoint remains approved; default configuration
            # consumes it once by recording the resumed state instead.
            approval.status = ApprovalStatus.RESUMED
            approval.resumed_by = actor
            approval.resumed_at = datetime.now(timezone.utc)
        doc.events.append(
            BlackboardEvent(
                actor=actor,
                op="approval.resumed",
                path=approval.artifact_path,
                after=approval.model_dump(mode="json"),
            )
        )
        return self.save(doc, expected_revision=expected_revision)

    @staticmethod
    def _require_revision(doc: BlackboardDocument, expected_revision: int) -> None:
        """Require callers to explicitly bind an approval mutation to a read."""
        if doc.revision != expected_revision:
            raise RevisionConflictError(
                f"Expected revision {expected_revision}, found {doc.revision}."
            )

    @staticmethod
    def _find_approval(doc: BlackboardDocument, approval_id: str) -> ApprovalRecord:
        for approval in doc.approvals:
            if approval.approval_id == approval_id:
                return approval
        raise ApprovalNotFoundError(f"Approval {approval_id!r} was not found.")

    @staticmethod
    def _assert_approval_actionable(
        doc: BlackboardDocument, approval: ApprovalRecord
    ) -> None:
        """Reject expiry or changed reviewed content before a decision/resume."""
        if approval.expires_at is not None and approval.expires_at <= datetime.now(
            timezone.utc
        ):
            raise InvalidApprovalTransitionError("Cannot act on an expired approval.")
        # Legacy records have no snapshot and remain actionable; new records
        # always capture one, including a legitimate null artifact value.
        if approval.artifact_snapshot_available and (
            not has_path(doc.data, approval.artifact_path)
            or not _same_artifact_value(
                get_path_value(doc.data, approval.artifact_path),
                approval.artifact_snapshot,
            )
        ):
            raise ApprovalArtifactChangedError(
                "Approval artifact changed after it was proposed; create a new approval."
            )


def bump_revision(doc: BlackboardDocument) -> BlackboardDocument:
    doc.revision += 1
    doc.updated_at = datetime.now(timezone.utc)
    return doc


def create_blackboard_store(
    store_config: dict | BlackboardStoreConfig,
) -> BlackboardStore:
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
        from automa_ai.blackboard.backends.dynamodb_json import (
            DynamoDBJSONBlackboardStore,
        )

        BlackboardStoreRegistry.register(
            BlackboardBackend.LOCAL_JSON, LocalJSONBlackboardStore
        )
        BlackboardStoreRegistry.register(
            BlackboardBackend.S3_JSON, S3JSONBlackboardStore
        )
        BlackboardStoreRegistry.register(
            BlackboardBackend.DYNAMODB_JSON, DynamoDBJSONBlackboardStore
        )
