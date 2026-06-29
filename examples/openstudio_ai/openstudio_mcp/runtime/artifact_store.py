from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from examples.openstudio_ai.openstudio_mcp.runtime.state_store import RuntimeStateStore


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    created_at: str
    parent_id: str | None
    kind: str
    tool_trace_id: str | None
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ArtifactStore:
    """Artifact registry with in-memory cache and optional SQLite persistence."""

    def __init__(self, state_store: RuntimeStateStore | None = None):
        self._items: dict[str, ArtifactRecord] = {}
        self.state_store = state_store

    def create(
        self,
        *,
        kind: str,
        metadata: dict[str, Any],
        parent_id: str | None = None,
        tool_trace_id: str | None = None,
    ) -> ArtifactRecord:
        artifact = ArtifactRecord(
            artifact_id=str(uuid4()),
            created_at=datetime.now(timezone.utc).isoformat(),
            parent_id=parent_id,
            kind=kind,
            tool_trace_id=tool_trace_id,
            metadata=dict(metadata),
        )
        self._items[artifact.artifact_id] = artifact
        if self.state_store is not None:
            self.state_store.upsert_artifact(
                artifact_id=artifact.artifact_id,
                created_at=artifact.created_at,
                parent_id=artifact.parent_id,
                kind=artifact.kind,
                tool_trace_id=artifact.tool_trace_id,
                metadata=artifact.metadata,
            )
        return artifact

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        item = self._items.get(artifact_id)
        if item is not None:
            if self.state_store is not None:
                self.state_store.touch_artifact(artifact_id)
            return item
        if self.state_store is None:
            return None
        persisted = self.state_store.get_artifact(artifact_id)
        if persisted is None or persisted["status"] != "available":
            return None
        artifact = ArtifactRecord(
            artifact_id=persisted["artifact_id"],
            created_at=persisted["created_at"],
            parent_id=persisted["parent_id"],
            kind=persisted["kind"],
            tool_trace_id=persisted["tool_trace_id"],
            metadata=persisted["metadata"],
        )
        self._items[artifact.artifact_id] = artifact
        self.state_store.touch_artifact(artifact_id)
        return artifact

    def must_get(self, artifact_id: str) -> ArtifactRecord:
        item = self.get(artifact_id)
        if not item:
            raise KeyError(f"Artifact not found: {artifact_id}")
        return item
