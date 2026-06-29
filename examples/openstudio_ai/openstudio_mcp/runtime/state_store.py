from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp for registry records."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class WorkspaceRecord:
    workspace_id: str
    kind: str
    path: str
    status: str
    created_at: str
    updated_at: str
    last_accessed_at: str
    job_id: str | None
    model_id: str | None
    artifact_id: str | None
    size_bytes: int
    pinned: bool
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeStateStore:
    """SQLite-backed local registry for MCP artifacts, jobs, and workspaces.

    The registry stores metadata only. Heavy files such as OSM, SQL, and logs
    remain on disk under the workspace root and are pruned through registry
    decisions.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    parent_id TEXT,
                    kind TEXT NOT NULL,
                    tool_trace_id TEXT,
                    metadata_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available',
                    pinned INTEGER NOT NULL DEFAULT 0,
                    last_accessed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_accessed_at TEXT NOT NULL,
                    job_id TEXT,
                    model_id TEXT,
                    artifact_id TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    run_mode TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    warnings_count INTEGER NOT NULL DEFAULT 0,
                    severe_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    artifacts_json TEXT NOT NULL,
                    error_json TEXT
                );
                """
            )

    def upsert_artifact(
        self,
        *,
        artifact_id: str,
        created_at: str,
        parent_id: str | None,
        kind: str,
        tool_trace_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (
                    artifact_id, created_at, parent_id, kind, tool_trace_id,
                    metadata_json, status, pinned, last_accessed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'available', 0, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    parent_id = excluded.parent_id,
                    kind = excluded.kind,
                    tool_trace_id = excluded.tool_trace_id,
                    metadata_json = excluded.metadata_json,
                    last_accessed_at = excluded.last_accessed_at
                """,
                (
                    artifact_id,
                    created_at,
                    parent_id,
                    kind,
                    tool_trace_id,
                    json.dumps(metadata, sort_keys=True),
                    utc_now(),
                ),
            )

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        return self._artifact_row_to_dict(row) if row else None

    def touch_artifact(self, artifact_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE artifacts SET last_accessed_at = ? WHERE artifact_id = ?",
                (utc_now(), artifact_id),
            )

    def mark_artifact_status(self, artifact_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE artifacts SET status = ?, last_accessed_at = ? WHERE artifact_id = ?",
                (status, utc_now(), artifact_id),
            )

    def pin_artifact(self, artifact_id: str, pinned: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE artifacts SET pinned = ?, last_accessed_at = ? WHERE artifact_id = ?",
                (1 if pinned else 0, utc_now(), artifact_id),
            )

    def upsert_workspace(
        self,
        *,
        workspace_id: str,
        kind: str,
        path: str | Path,
        job_id: str | None = None,
        model_id: str | None = None,
        artifact_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        size_bytes: int = 0,
    ) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workspaces (
                    workspace_id, kind, path, status, created_at, updated_at,
                    last_accessed_at, job_id, model_id, artifact_id, size_bytes,
                    pinned, metadata_json
                )
                VALUES (?, ?, ?, 'available', ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                    kind = excluded.kind,
                    path = excluded.path,
                    updated_at = excluded.updated_at,
                    last_accessed_at = excluded.last_accessed_at,
                    job_id = COALESCE(excluded.job_id, workspaces.job_id),
                    model_id = COALESCE(excluded.model_id, workspaces.model_id),
                    artifact_id = COALESCE(excluded.artifact_id, workspaces.artifact_id),
                    size_bytes = excluded.size_bytes,
                    metadata_json = excluded.metadata_json
                """,
                (
                    workspace_id,
                    kind,
                    str(Path(path).resolve()),
                    now,
                    now,
                    now,
                    job_id,
                    model_id,
                    artifact_id,
                    size_bytes,
                    json.dumps(metadata or {}, sort_keys=True),
                ),
            )

    def touch_workspace(
        self, workspace_id: str, *, size_bytes: int | None = None
    ) -> None:
        assignments = ["last_accessed_at = ?", "updated_at = ?"]
        values: list[Any] = [utc_now(), utc_now()]
        if size_bytes is not None:
            assignments.append("size_bytes = ?")
            values.append(size_bytes)
        values.append(workspace_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE workspaces SET {', '.join(assignments)} WHERE workspace_id = ?",
                values,
            )

    def mark_workspace_status(self, workspace_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE workspaces
                SET status = ?, updated_at = ?, last_accessed_at = ?
                WHERE workspace_id = ?
                """,
                (status, utc_now(), utc_now(), workspace_id),
            )

    def list_workspaces(self) -> list[WorkspaceRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workspaces ORDER BY created_at"
            ).fetchall()
        return [self._workspace_row_to_record(row) for row in rows]

    def upsert_job(
        self,
        *,
        job_id: str,
        model_id: str,
        run_mode: str,
        options: dict[str, Any],
        state: str,
        progress: int,
        warnings_count: int,
        severe_count: int,
        created_at: str,
        updated_at: str,
        artifacts: dict[str, str],
        error: dict[str, Any] | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, model_id, run_mode, options_json, state, progress,
                    warnings_count, severe_count, created_at, updated_at,
                    artifacts_json, error_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    model_id = excluded.model_id,
                    run_mode = excluded.run_mode,
                    options_json = excluded.options_json,
                    state = excluded.state,
                    progress = excluded.progress,
                    warnings_count = excluded.warnings_count,
                    severe_count = excluded.severe_count,
                    updated_at = excluded.updated_at,
                    artifacts_json = excluded.artifacts_json,
                    error_json = excluded.error_json
                """,
                (
                    job_id,
                    model_id,
                    run_mode,
                    json.dumps(options, sort_keys=True),
                    state,
                    progress,
                    warnings_count,
                    severe_count,
                    created_at,
                    updated_at,
                    json.dumps(artifacts, sort_keys=True),
                    json.dumps(error, sort_keys=True) if error is not None else None,
                ),
            )

    def workspace_usage(self) -> dict[str, Any]:
        records = self.list_workspaces()
        by_kind: dict[str, dict[str, int]] = {}
        for record in records:
            bucket = by_kind.setdefault(record.kind, {"count": 0, "size_bytes": 0})
            bucket["count"] += 1
            bucket["size_bytes"] += record.size_bytes
        return {
            "db_path": str(self.db_path),
            "workspace_count": len(records),
            "total_size_bytes": sum(record.size_bytes for record in records),
            "by_kind": by_kind,
            "workspaces": [record.to_dict() for record in records],
        }

    @staticmethod
    def _artifact_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "artifact_id": row["artifact_id"],
            "created_at": row["created_at"],
            "parent_id": row["parent_id"],
            "kind": row["kind"],
            "tool_trace_id": row["tool_trace_id"],
            "metadata": json.loads(row["metadata_json"]),
            "status": row["status"],
            "pinned": bool(row["pinned"]),
            "last_accessed_at": row["last_accessed_at"],
        }

    @staticmethod
    def _workspace_row_to_record(row: sqlite3.Row) -> WorkspaceRecord:
        return WorkspaceRecord(
            workspace_id=row["workspace_id"],
            kind=row["kind"],
            path=row["path"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_accessed_at=row["last_accessed_at"],
            job_id=row["job_id"],
            model_id=row["model_id"],
            artifact_id=row["artifact_id"],
            size_bytes=int(row["size_bytes"]),
            pinned=bool(row["pinned"]),
            metadata=json.loads(row["metadata_json"]),
        )


def sum_file_sizes(paths: Iterable[Path]) -> int:
    """Return total bytes for existing files under the given paths."""
    total = 0
    for root in paths:
        if root.is_file():
            total += root.stat().st_size
        elif root.exists():
            for path in root.rglob("*"):
                if path.is_file():
                    total += path.stat().st_size
    return total
