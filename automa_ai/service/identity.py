from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


TRUSTED_IDENTITY_METADATA_KEYS = frozenset(
    {
        "auth.trusted",
        "subject",
        "user_id",
        "tenant_id",
        "groups",
        "scopes",
    }
)


class Principal(BaseModel):
    """Trusted identity extracted at the service boundary."""

    subject: str
    user_id: str
    tenant_id: str | None = None
    groups: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    claims: dict[str, Any] = Field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        metadata = {
            "auth.trusted": True,
            "subject": self.subject,
            "user_id": self.user_id,
            "groups": list(self.groups),
            "scopes": list(self.scopes),
        }
        if self.tenant_id is not None:
            metadata["tenant_id"] = self.tenant_id
        return metadata
