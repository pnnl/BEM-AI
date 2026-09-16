from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from automa_ai.blackboard.backends.local_json import LocalJSONBlackboardStore
from automa_ai.blackboard.errors import (
    ApprovalArtifactChangedError,
    InvalidApprovalTransitionError,
    RevisionConflictError,
)
from automa_ai.blackboard.approvals import ApprovalManager
from automa_ai.blackboard.models import (
    ApprovalStatus,
    BlackboardDocument,
    BlackboardPatch,
)
from automa_ai.blackboard.schema import BlackboardSchemaRegistry
from automa_ai.blackboard.store import BlackboardStoreConfig
from automa_ai.blackboard.tools import build_blackboard_tools
from automa_ai.config.blackboard import BlackboardConfig


@pytest.fixture
def session_id() -> str:
    return "approval-session"


@pytest.fixture
def store(tmp_path, session_id):
    BlackboardSchemaRegistry.register(
        name="approval-test",
        version="1",
        json_schema={
            "type": "object",
            "properties": {"items": {"type": "array"}},
            "required": ["items"],
        },
    )
    store = LocalJSONBlackboardStore(
        BlackboardStoreConfig(backend="local_json", base_dir=str(tmp_path))
    )
    store.create(session_id, "approval-test", "1", {"items": ["draft"]})
    return store


def test_approval_lifecycle_is_revisioned_and_persistent(store, session_id) -> None:
    proposed = store.propose_approval(
        session_id,
        "items",
        actor="agent-a",
        title="Review draft",
        expected_revision=1,
    )
    approval = proposed.approvals[0]
    assert approval.status is ApprovalStatus.PENDING
    assert approval.artifact_revision == 1
    assert approval.artifact_snapshot == ["draft"]
    assert approval.artifact_snapshot_available
    assert proposed.events[-1].op == "approval.proposed"

    approved = store.resolve_approval(
        session_id,
        approval.approval_id,
        "approved",
        reviewer="reviewer-1",
        note="Looks good",
        expected_revision=2,
    )
    assert approved.approvals[0].status is ApprovalStatus.APPROVED
    assert approved.approvals[0].reviewer == "reviewer-1"

    resumed = store.claim_approved_resume(
        session_id,
        approval.approval_id,
        actor="workflow",
        expected_revision=3,
    )
    assert resumed.approvals[0].status is ApprovalStatus.RESUMED
    assert store.load(session_id).approvals[0].resumed_by == "workflow"
    assert [event.op for event in resumed.events[-3:]] == [
        "approval.proposed",
        "approval.approved",
        "approval.resumed",
    ]


def test_approval_rejects_stale_and_invalid_transitions(store, session_id) -> None:
    proposed = store.propose_approval(session_id, "items", expected_revision=1)
    approval_id = proposed.approvals[0].approval_id

    with pytest.raises(RevisionConflictError):
        store.resolve_approval(
            session_id,
            approval_id,
            "approved",
            reviewer="reviewer-1",
            expected_revision=1,
        )

    store.resolve_approval(
        session_id,
        approval_id,
        "rejected",
        reviewer="reviewer-1",
        expected_revision=2,
    )
    with pytest.raises(InvalidApprovalTransitionError):
        store.resolve_approval(
            session_id,
            approval_id,
            "approved",
            reviewer="reviewer-2",
            expected_revision=3,
        )
    with pytest.raises(InvalidApprovalTransitionError):
        store.claim_approved_resume(session_id, approval_id, expected_revision=3)


def test_approval_mutations_require_a_revision(store, session_id) -> None:
    with pytest.raises(TypeError):
        store.propose_approval(session_id, "items")


def test_agent_approval_tools_are_opt_in_and_cannot_resolve(store, session_id) -> None:
    disabled = {tool.name for tool in build_blackboard_tools(store)}
    enabled = {
        tool.name for tool in build_blackboard_tools(store, approvals={"enabled": True})
    }
    assert "blackboard_request_approval" not in disabled
    assert {"blackboard_request_approval", "blackboard_get_approval"} <= enabled
    assert "blackboard_resolve_approval" not in enabled

    tools = {
        tool.name: tool
        for tool in build_blackboard_tools(store, approvals={"enabled": True})
    }
    result = tools["blackboard_request_approval"].func(
        session_id=session_id,
        artifact_path="items",
        expected_revision=1,
        actor="agent-a",
    )
    approval_id = result["approval"]["approval_id"]
    assert (
        tools["blackboard_get_approval"].func(
            session_id=session_id, approval_id=approval_id
        )["approval"]["status"]
        == "pending"
    )


def test_approval_list_filters_by_status(store, session_id) -> None:
    first = store.propose_approval(session_id, "items", expected_revision=1)
    store.propose_approval(session_id, "items", expected_revision=2)
    store.resolve_approval(
        session_id,
        first.approvals[0].approval_id,
        ApprovalStatus.APPROVED,
        reviewer="reviewer-1",
        expected_revision=3,
    )
    assert len(store.list_approvals(session_id, status="pending")) == 1
    assert len(store.list_approvals(session_id, status=ApprovalStatus.APPROVED)) == 1


def test_approval_manager_applies_configured_resume_policy(store, session_id) -> None:
    manager = ApprovalManager(store, {"enabled": True, "allow_one_time_resume": False})
    proposed = manager.request(session_id, "items", expected_revision=1)
    approval_id = proposed.approvals[0].approval_id
    approved = manager.resolve(
        session_id,
        approval_id,
        "approved",
        reviewer="reviewer-1",
        expected_revision=2,
    )
    resumed = manager.resume(
        session_id, approval_id, expected_revision=approved.revision
    )
    assert resumed.approvals[0].status is ApprovalStatus.APPROVED


def test_approval_manager_requires_explicit_opt_in(store) -> None:
    with pytest.raises(ValueError, match="approvals.enabled=true"):
        ApprovalManager(store)


def test_approval_rejects_artifact_drift_and_expiry(store, session_id) -> None:
    proposed = store.propose_approval(session_id, "items", expected_revision=1)
    approval_id = proposed.approvals[0].approval_id
    store.apply_patch(
        session_id,
        BlackboardPatch(ops=[{"op": "append", "path": "items", "value": "changed"}]),
        expected_revision=2,
    )
    with pytest.raises(ApprovalArtifactChangedError):
        store.resolve_approval(
            session_id,
            approval_id,
            "approved",
            reviewer="reviewer-1",
            expected_revision=3,
        )

    proposed = store.propose_approval(session_id, "items", expected_revision=3)
    document = store.load(session_id)
    document.approvals[-1].expires_at = datetime.now(timezone.utc) - timedelta(
        seconds=1
    )
    store.save(document, expected_revision=4)
    with pytest.raises(InvalidApprovalTransitionError, match="expired"):
        store.resolve_approval(
            session_id,
            proposed.approvals[-1].approval_id,
            "approved",
            reviewer="reviewer-1",
            expected_revision=5,
        )


def test_approval_accepts_existing_null_artifact(store, session_id) -> None:
    document = store.apply_patch(
        session_id,
        BlackboardPatch(ops=[{"op": "set", "path": "nullable", "value": None}]),
        expected_revision=1,
    )
    proposed = store.propose_approval(
        session_id, "nullable", expected_revision=document.revision
    )
    assert proposed.approvals[0].artifact_snapshot is None


def test_legacy_approval_without_snapshot_loads_and_remains_actionable(
    store, session_id
) -> None:
    payload = store.load(session_id).to_json_dict()
    payload["approvals"] = [
        {
            "approval_id": "legacy",
            "status": "pending",
            "artifact_path": "items",
            "artifact_revision": 1,
        }
    ]
    legacy = BlackboardDocument.from_json_dict(payload)
    store.save(legacy, expected_revision=1)
    resolved = store.resolve_approval(
        session_id,
        "legacy",
        "approved",
        reviewer="reviewer-1",
        expected_revision=2,
    )
    assert resolved.approvals[0].status is ApprovalStatus.APPROVED
    assert not resolved.approvals[0].artifact_snapshot_available


def test_blackboard_config_defaults_approvals_off_and_accepts_opt_in() -> None:
    disabled = BlackboardConfig(
        enabled=True,
        store={"backend": "local_json", "base_dir": ".blackboard"},
        schema_name="approval-test",
        schema_version="1",
    )
    enabled = BlackboardConfig(
        enabled=True,
        store={"backend": "local_json", "base_dir": ".blackboard"},
        schema_name="approval-test",
        schema_version="1",
        approvals={"enabled": True, "default_expiry_seconds": 60},
    )
    assert not disabled.approvals.enabled
    assert enabled.approvals.enabled
    assert enabled.approvals.default_expiry_seconds == 60
