from __future__ import annotations

from typing import Any

from automa_ai.agents.remote_agent import get_subagent_context_id

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from automa_ai.blackboard.models import BlackboardPatch
from automa_ai.blackboard.store import BlackboardStore, get_path_value
from automa_ai.config.blackboard import ApprovalConfig


class BlackboardReadInput(BaseModel):
    session_id: str | None = None
    path: str | None = None


class BlackboardWriteInput(BaseModel):
    session_id: str | None = None
    ops: list[dict[str, Any]] = Field(default_factory=list)
    expected_revision: int | None = None
    actor: str | None = None
    note: str | None = None


class BlackboardRevisionInput(BaseModel):
    session_id: str | None = None


class BlackboardApprovalRequestInput(BaseModel):
    artifact_path: str
    session_id: str | None = None
    expected_revision: int
    actor: str | None = None
    title: str | None = None
    note: str | None = None


class BlackboardApprovalGetInput(BaseModel):
    approval_id: str
    session_id: str | None = None


def build_blackboard_tools(
    store: BlackboardStore,
    *,
    approvals: ApprovalConfig | dict[str, Any] | None = None,
) -> list[StructuredTool]:
    """Build safe agent tools, exposing approval requests only when enabled."""
    if approvals is not None and not isinstance(approvals, ApprovalConfig):
        approvals = ApprovalConfig.model_validate(approvals)

    def _resolve_session_id(session_id: str | None) -> str:
        # Prompts must not expose a runtime session identifier to an LLM.  Accept
        # the placeholder emitted by older examples as an omitted value so that a
        # running request still resolves to its actual context ID.
        if session_id in {"current_session_id", "<current_session_id>"}:
            session_id = None
        resolved = session_id or get_subagent_context_id()
        if not resolved:
            raise ValueError(
                "session_id is required when no active request context is available."
            )
        return resolved

    def blackboard_read(
        session_id: str | None = None, path: str | None = None
    ) -> dict[str, Any]:
        resolved_session_id = _resolve_session_id(session_id)
        doc = store.load(resolved_session_id)
        data = get_path_value(doc.data, path)
        return {
            "session_id": resolved_session_id,
            "revision": doc.revision,
            "updated_at": doc.updated_at.isoformat(),
            "path": path,
            "data": data,
        }

    def blackboard_write(
        ops: list[dict[str, Any]],
        session_id: str | None = None,
        expected_revision: int | None = None,
        actor: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        resolved_session_id = _resolve_session_id(session_id)
        patch = BlackboardPatch(ops=ops, actor=actor, note=note)
        doc = store.apply_patch(
            session_id=resolved_session_id,
            patch=patch,
            expected_revision=expected_revision,
        )
        return {
            "session_id": resolved_session_id,
            "revision": doc.revision,
            "updated_at": doc.updated_at.isoformat(),
            "event_count": len(doc.events),
        }

    def blackboard_get_revision(session_id: str | None = None) -> dict[str, Any]:
        resolved_session_id = _resolve_session_id(session_id)
        doc = store.load(resolved_session_id)
        return {
            "session_id": resolved_session_id,
            "revision": doc.revision,
            "updated_at": doc.updated_at.isoformat(),
        }

    def blackboard_request_approval(
        artifact_path: str,
        expected_revision: int,
        session_id: str | None = None,
        actor: str | None = None,
        title: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Create a pending review; agents cannot resolve their own requests."""
        resolved_session_id = _resolve_session_id(session_id)
        doc = store.propose_approval(
            resolved_session_id,
            artifact_path,
            actor=actor,
            title=title,
            note=note,
            expiry_seconds=approvals.default_expiry_seconds if approvals else None,
            expected_revision=expected_revision,
        )
        approval = doc.approvals[-1]
        return {
            "session_id": resolved_session_id,
            "revision": doc.revision,
            "approval": approval.model_dump(mode="json"),
        }

    def blackboard_get_approval(
        approval_id: str, session_id: str | None = None
    ) -> dict[str, Any]:
        """Read one pending or resolved approval without authorizing a decision."""
        resolved_session_id = _resolve_session_id(session_id)
        return {
            "session_id": resolved_session_id,
            "approval": store.get_approval(resolved_session_id, approval_id).model_dump(
                mode="json"
            ),
        }

    tools = [
        StructuredTool.from_function(
            name="blackboard_read",
            description="Read the session blackboard document or a specific path. Omit session_id during an agent request; the active request context is used.",
            func=blackboard_read,
            args_schema=BlackboardReadInput,
        ),
        StructuredTool.from_function(
            name="blackboard_write",
            description="Apply deterministic write operations to the session blackboard. Omit session_id during an agent request; the active request context is used.",
            func=blackboard_write,
            args_schema=BlackboardWriteInput,
        ),
        StructuredTool.from_function(
            name="blackboard_get_revision",
            description="Return the current revision for session blackboard. Omit session_id during an agent request; the active request context is used.",
            func=blackboard_get_revision,
            args_schema=BlackboardRevisionInput,
        ),
    ]
    if approvals and approvals.enabled:
        tools.extend(
            [
                StructuredTool.from_function(
                    name="blackboard_request_approval",
                    description="Request human review for an existing blackboard artifact. This tool cannot approve or reject the request.",
                    func=blackboard_request_approval,
                    args_schema=BlackboardApprovalRequestInput,
                ),
                StructuredTool.from_function(
                    name="blackboard_get_approval",
                    description="Read one human approval request and its durable decision state.",
                    func=blackboard_get_approval,
                    args_schema=BlackboardApprovalGetInput,
                ),
            ]
        )
    return tools
