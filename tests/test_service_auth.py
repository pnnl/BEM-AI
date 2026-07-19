from __future__ import annotations

from unittest.mock import Mock

import pytest
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from automa_ai.config.service import (
    ServiceAuthConfig,
    ServiceConfig,
    ServiceIdentityConfig,
)
from automa_ai.service.auth import AuthError, AuthProvider, principal_from_claims
from automa_ai.service.identity import Principal
from automa_ai.service.middleware import (
    AuthMiddleware,
    AutomaServerCallContextBuilder,
    PRINCIPAL_STATE_KEY,
)


def test_cognito_auth_config_derives_issuer_and_jwks_url() -> None:
    config = ServiceAuthConfig(
        enabled=True,
        provider="cognito",
        region="us-west-2",
        user_pool_id="us-west-2_abc123",
    )

    assert config.resolved_issuer == (
        "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_abc123"
    )
    assert config.resolved_jwks_url == (
        "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_abc123"
        "/.well-known/jwks.json"
    )


def test_jwt_auth_config_requires_jwks_when_enabled() -> None:
    with pytest.raises(ValueError, match="jwks_url"):
        ServiceAuthConfig(enabled=True, provider="jwt", issuer="https://issuer")


def test_principal_from_claims_uses_configured_claims() -> None:
    principal = principal_from_claims(
        {
            "sub": "subject",
            "custom:user_id": "user-1",
            "custom:tenant_id": "tenant-1",
            "cognito:groups": ["operators"],
            "scope": "automa:invoke other:scope",
        },
        ServiceIdentityConfig(
            user_id_claim="custom:user_id",
            tenant_id_claim="custom:tenant_id",
            groups_claim="cognito:groups",
        ),
    )

    assert principal.subject == "subject"
    assert principal.user_id == "user-1"
    assert principal.tenant_id == "tenant-1"
    assert principal.groups == ["operators"]
    assert principal.scopes == ["automa:invoke", "other:scope"]


class StaticAuthProvider(AuthProvider):
    def __init__(
        self, principal: Principal | None = None, error: AuthError | None = None
    ):
        self.principal = principal
        self.error = error

    def authenticate(self, authorization: str | None) -> Principal:
        if self.error is not None:
            raise self.error
        assert self.principal is not None
        return self.principal


def test_auth_middleware_attaches_principal_to_request_state() -> None:
    principal = Principal(subject="sub", user_id="user")

    async def endpoint(request):
        return JSONResponse(request.state.automa_principal.to_metadata())

    app = Starlette(routes=[Route("/", endpoint)])
    app.add_middleware(AuthMiddleware, auth_provider=StaticAuthProvider(principal))

    response = TestClient(app).get("/", headers={"authorization": "Bearer token"})

    assert response.status_code == 200
    assert response.json()["auth.trusted"] is True
    assert response.json()["user_id"] == "user"


def test_auth_middleware_returns_401_for_auth_error() -> None:
    async def endpoint(request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/", endpoint)])
    app.add_middleware(
        AuthMiddleware,
        auth_provider=StaticAuthProvider(
            error=AuthError("Missing Authorization header.", status_code=401)
        ),
    )

    response = TestClient(app).get("/")

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_auth_middleware_allows_public_paths() -> None:
    async def endpoint(request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/health", endpoint)])
    app.add_middleware(
        AuthMiddleware,
        auth_provider=StaticAuthProvider(
            error=AuthError("Missing Authorization header.", status_code=401)
        ),
        public_paths=["/health"],
    )

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_context_builder_copies_principal_from_request_state() -> None:
    request = Mock()
    request.headers = Headers({})
    request.scope = {}
    request.state = Mock()
    request.state.automa_principal = Principal(
        subject="sub",
        user_id="user",
        tenant_id="tenant",
    )

    context = AutomaServerCallContextBuilder().build(request)

    assert context.state[PRINCIPAL_STATE_KEY].user_id == "user"
    assert context.state["automa_identity"]["auth.trusted"] is True
    assert context.tenant == "tenant"


def test_service_config_defaults_to_disabled_auth() -> None:
    config = ServiceConfig.from_value(None)

    assert config.auth.enabled is False
