from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from examples.openstudio_ai.openstudio_mcp.runtime.artifact_store import ArtifactStore
from examples.openstudio_ai.openstudio_mcp.runtime.workspace_manager import WorkspaceManager

JobState = Literal["RUNNING", "SUCCEEDED", "FAILED"]


@dataclass
class JobRecord:
    job_id: str
    model_id: str
    run_mode: str
    options: dict[str, Any]
    state: JobState
    progress: int
    warnings_count: int
    severe_count: int
    created_at: str
    updated_at: str
    artifacts: dict[str, str] = field(default_factory=dict)
    error: dict[str, Any] | None = None


class JobManager:
    def __init__(self, workspace_manager: WorkspaceManager, artifact_store: ArtifactStore):
        self.workspace_manager = workspace_manager
        self.artifact_store = artifact_store
        self._jobs: dict[str, JobRecord] = {}

    def create_job(self, *, model_id: str, run_mode: str, options: dict[str, Any]) -> JobRecord:
        now = datetime.now(timezone.utc).isoformat()
        job = JobRecord(
            job_id=str(uuid4()),
            model_id=model_id,
            run_mode=run_mode,
            options=dict(options),
            state="RUNNING",
            progress=0,
            warnings_count=0,
            severe_count=0,
            created_at=now,
            updated_at=now,
        )
        self._jobs[job.job_id] = job
        self.workspace_manager.create_workspace(job.job_id)
        return job

    def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def mark_running(self, job_id: str, *, progress: int | None = None) -> None:
        job = self._jobs[job_id]
        job.state = "RUNNING"
        if progress is not None:
            job.progress = progress
        job.updated_at = datetime.now(timezone.utc).isoformat()

    def mark_succeeded(
        self,
        job_id: str,
        *,
        artifacts: dict[str, str],
        warnings_count: int = 0,
        severe_count: int = 0,
    ) -> None:
        job = self._jobs[job_id]
        job.state = "SUCCEEDED"
        job.progress = 100
        job.warnings_count = warnings_count
        job.severe_count = severe_count
        job.artifacts = dict(artifacts)
        job.updated_at = datetime.now(timezone.utc).isoformat()

    async def complete_stub_simulation(self, job_id: str, *, model_id: str) -> None:
        job = self._jobs[job_id]
        await asyncio.sleep(0.05)

        osm = self.artifact_store.create(
            kind="osm",
            parent_id=model_id,
            metadata={"job_id": job_id, "source": "stub_simulation"},
        )
        sql = self.artifact_store.create(
            kind="sql",
            parent_id=osm.artifact_id,
            metadata={"job_id": job_id, "query_types": ["sizing_summary"]},
        )
        logs = self.artifact_store.create(
            kind="logs",
            parent_id=osm.artifact_id,
            metadata={"job_id": job_id},
        )
        report = self.artifact_store.create(
            kind="report",
            parent_id=sql.artifact_id,
            metadata={"job_id": job_id, "format": "json"},
        )

        now = datetime.now(timezone.utc).isoformat()
        job.state = "SUCCEEDED"
        job.progress = 100
        job.updated_at = now
        job.artifacts = {
            "osm_id": osm.artifact_id,
            "sql_id": sql.artifact_id,
            "logs_id": logs.artifact_id,
            "report_id": report.artifact_id,
        }

    def fail(self, job_id: str, *, error: dict[str, Any]) -> None:
        job = self._jobs[job_id]
        job.state = "FAILED"
        job.progress = 100
        job.error = error
        job.updated_at = datetime.now(timezone.utc).isoformat()
