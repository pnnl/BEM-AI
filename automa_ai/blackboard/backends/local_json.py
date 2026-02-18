from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from automa_ai.blackboard.errors import DocumentNotFoundError, RevisionConflictError
from automa_ai.blackboard.models import BlackboardDocument
from automa_ai.blackboard.store import BlackboardStore, bump_revision


class LocalJSONBlackboardStore(BlackboardStore):
    def __init__(self, base_dir: str, validator):
        super().__init__(validator)
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        if not session_id or session_id in {".", ".."}:
            raise ValueError("session_id must be a non-empty, path-safe identifier.")
        if "/" in session_id or "\\" in session_id:
            raise ValueError("session_id must not include path separators.")
        return self.base_dir / f"{session_id}.blackboard.json"

    def load(self, session_id: str) -> BlackboardDocument:
        path = self._path(session_id)
        if not path.exists():
            raise DocumentNotFoundError(f"Session '{session_id}' has no blackboard document.")
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        return BlackboardDocument.from_json_dict(payload)

    def create(
        self,
        session_id: str,
        schema_name: str,
        schema_version: str,
        initial_data: dict[str, Any] | None = None,
    ) -> BlackboardDocument:
        doc = BlackboardDocument(
            session_id=session_id,
            schema_name=schema_name,
            schema_version=schema_version,
            data=initial_data or {},
        )
        self.validator.validate(schema_name, schema_version, doc.data)
        return self.save(doc, expected_revision=None)

    def save(self, doc: BlackboardDocument, expected_revision: int | None = None) -> BlackboardDocument:
        path = self._path(doc.session_id)
        if path.exists():
            existing = self.load(doc.session_id)
            if expected_revision is not None and existing.revision != expected_revision:
                raise RevisionConflictError(
                    f"Expected revision {expected_revision}, found {existing.revision}."
                )
            if expected_revision is None:
                doc.revision = existing.revision
        bump_revision(doc)

        fd, tmp_name = tempfile.mkstemp(dir=self.base_dir, prefix=".blackboard.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(doc.to_json_dict(), f, indent=2)
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        return doc
