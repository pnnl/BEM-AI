from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


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
    """In-memory immutable artifact store for infra tests and local development."""

    def __init__(self):
        self._items: dict[str, ArtifactRecord] = {}

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
        return artifact

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        return self._items.get(artifact_id)

    def must_get(self, artifact_id: str) -> ArtifactRecord:
        item = self.get(artifact_id)
        if not item:
            raise KeyError(f"Artifact not found: {artifact_id}")
        return item
