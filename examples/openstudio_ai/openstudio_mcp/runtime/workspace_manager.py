from __future__ import annotations

import shutil
from pathlib import Path


class WorkspaceManager:
    """Creates per-job sandbox directories and guards path traversal."""

    def __init__(
        self, root_dir: str | Path, max_workspace_bytes: int = 100 * 1024 * 1024
    ):
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.max_workspace_bytes = max_workspace_bytes

    def create_workspace(self, job_id: str) -> Path:
        workspace = (self.root_dir / job_id).resolve()
        if self.root_dir not in workspace.parents and workspace != self.root_dir:
            raise ValueError("Workspace path traversal is not allowed")
        workspace.mkdir(parents=True, exist_ok=True)
        self.ensure_quota(job_id)
        return workspace

    def resolve_path(self, job_id: str, relative_path: str) -> Path:
        workspace = self.create_workspace(job_id)
        candidate = (workspace / relative_path).resolve()
        if workspace not in candidate.parents and candidate != workspace:
            raise ValueError("Path traversal is not allowed")
        self.ensure_quota(job_id)
        return candidate

    def cleanup_workspace(self, job_id: str) -> None:
        workspace = (self.root_dir / job_id).resolve()
        if workspace.exists() and self.root_dir in workspace.parents:
            shutil.rmtree(workspace)

    def workspace_path(self, workspace_id: str) -> Path:
        workspace = (self.root_dir / workspace_id).resolve()
        if self.root_dir not in workspace.parents and workspace != self.root_dir:
            raise ValueError("Workspace path traversal is not allowed")
        return workspace

    def workspace_size(self, workspace_id: str) -> int:
        return self.path_size(self.workspace_path(workspace_id))

    def path_size(self, path: Path) -> int:
        if not path.exists():
            return 0
        if path.is_file():
            return path.stat().st_size
        total_bytes = 0
        for item in path.rglob("*"):
            if item.is_file():
                total_bytes += item.stat().st_size
        return total_bytes

    def ensure_quota(self, job_id: str) -> None:
        workspace = (self.root_dir / job_id).resolve()
        if not workspace.exists():
            return
        total_bytes = self.path_size(workspace)
        if total_bytes > self.max_workspace_bytes:
            raise ValueError(
                f"Workspace quota exceeded for {job_id}: {total_bytes} > {self.max_workspace_bytes}"
            )
