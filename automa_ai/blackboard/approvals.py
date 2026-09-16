"""Application-side API for durable blackboard approval checkpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from automa_ai.blackboard.models import ApprovalStatus, BlackboardDocument
from automa_ai.blackboard.store import BlackboardStore

if TYPE_CHECKING:
    from automa_ai.config.blackboard import ApprovalConfig


class ApprovalManager:
    """Apply an application's approval configuration to one blackboard store.

    This object is for authenticated host application code and is never exposed
    to an agent as a LangChain tool.
    """

    def __init__(
        self,
        store: BlackboardStore,
        config: "ApprovalConfig | dict[str, Any] | None" = None,
    ) -> None:
        # This import must stay local: importing config.blackboard first reaches
        # blackboard.__init__, which eagerly exports this manager.
        from automa_ai.config.blackboard import ApprovalConfig

        self.store = store
        self.config = (
            config
            if isinstance(config, ApprovalConfig)
            else ApprovalConfig.model_validate(config or {})
        )
        if not self.config.enabled:
            raise ValueError("ApprovalManager requires approvals.enabled=true.")

    def request(
        self, session_id: str, artifact_path: str, **kwargs: Any
    ) -> BlackboardDocument:
        """Record a pending review using the configured default expiry."""
        return self.store.propose_approval(
            session_id,
            artifact_path,
            expiry_seconds=self.config.default_expiry_seconds,
            **kwargs,
        )

    def resolve(
        self,
        session_id: str,
        approval_id: str,
        decision: ApprovalStatus | str,
        **kwargs: Any,
    ) -> BlackboardDocument:
        """Record an authenticated host application's decision."""
        return self.store.resolve_approval(session_id, approval_id, decision, **kwargs)

    def resume(
        self, session_id: str, approval_id: str, **kwargs: Any
    ) -> BlackboardDocument:
        """Consume an approved checkpoint using configured resume semantics."""
        return self.store.claim_approved_resume(
            session_id,
            approval_id,
            allow_one_time_resume=self.config.allow_one_time_resume,
            **kwargs,
        )
