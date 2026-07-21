from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ServiceIdentityConfig(BaseModel):
    """Claim mapping for trusted service identity."""

    user_id_claim: str = "sub"
    tenant_id_claim: str | None = None
    groups_claim: str = "groups"
    scopes_claim: str = "scope"

    model_config = ConfigDict(extra="forbid")


class ServiceAuthConfig(BaseModel):
    """Authentication settings for the A2A service boundary."""

    enabled: bool = False
    provider: Literal["jwt", "cognito"] = "jwt"
    issuer: str | None = None
    audience: str | list[str] | None = None
    jwks_url: str | None = None
    algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    required_scopes: list[str] = Field(default_factory=list)
    required_groups: list[str] = Field(default_factory=list)
    leeway_seconds: int = Field(default=0, ge=0)

    # Cognito convenience fields.
    region: str | None = None
    user_pool_id: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_provider_fields(self) -> "ServiceAuthConfig":
        if not self.enabled:
            return self

        if self.provider == "cognito":
            if self.region and self.user_pool_id:
                return self
            if self.issuer and self.jwks_url:
                return self
            raise ValueError(
                "Cognito auth requires region/user_pool_id or explicit issuer/jwks_url."
            )

        if not self.issuer:
            raise ValueError("JWT auth requires issuer.")
        if not self.jwks_url:
            raise ValueError("JWT auth requires jwks_url.")
        return self

    @property
    def resolved_issuer(self) -> str | None:
        if self.issuer:
            return self.issuer
        if self.provider == "cognito" and self.region and self.user_pool_id:
            return (
                f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"
            )
        return None

    @property
    def resolved_jwks_url(self) -> str | None:
        if self.jwks_url:
            return self.jwks_url
        issuer = self.resolved_issuer
        return f"{issuer.rstrip('/')}/.well-known/jwks.json" if issuer else None


class ServiceConfig(BaseModel):
    """Production service wrapper options for an A2A agent server."""

    auth: ServiceAuthConfig = Field(default_factory=ServiceAuthConfig)
    identity: ServiceIdentityConfig = Field(default_factory=ServiceIdentityConfig)

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_value(
        cls, value: "ServiceConfig | dict[str, Any] | None"
    ) -> "ServiceConfig":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        return cls.model_validate(value)
