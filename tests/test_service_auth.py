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
from automa_ai.service.auth import (
    AuthError,
    AuthProvider,
    CognitoAuthProvider,
    principal_from_claims,
)
from automa_ai.service.constants import IDENTITY_METADATA_STATE_KEY, PRINCIPAL_STATE_KEY
from automa_ai.service.identity import Principal
from automa_ai.service.middleware import (
    AuthMiddleware,
    AutomaServerCallContextBuilder,
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


def test_auth_config_derives_jwks_url_without_duplicate_slash() -> None:
    config = ServiceAuthConfig(
        provider="cognito",
        issuer="https://cognito-idp.us-west-2.amazonaws.com/us-west-2_abc123/",
    )

    assert config.resolved_jwks_url == (
        "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_abc123"
        "/.well-known/jwks.json"
    )


def test_jwt_auth_config_requires_jwks_when_enabled() -> None:
    with pytest.raises(ValueError, match="jwks_url"):
        ServiceAuthConfig(enabled=True, provider="jwt", issuer="https://issuer")


def test_auth_config_requires_algorithm_when_enabled() -> None:
    with pytest.raises(ValueError, match="at least one JWT algorithm"):
        ServiceAuthConfig(
            enabled=True,
            provider="jwt",
            issuer="https://issuer",
            jwks_url="https://issuer/.well-known/jwks.json",
            algorithms=[],
        )


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


class FakeSigningKey:
    key = "fake-key"


class FakeJWKClient:
    def get_signing_key_from_jwt(self, token: str):
        return FakeSigningKey()


def test_cognito_access_token_validates_client_id_not_audience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decode_kwargs = {}

    def fake_decode(token, signing_key, **kwargs):
        decode_kwargs.update(kwargs)
        return {
            "sub": "subject",
            "token_use": "access",
            "client_id": "client-id",
            "scope": "automa:invoke",
        }

    import jwt

    monkeypatch.setattr(jwt, "decode", fake_decode)
    provider = CognitoAuthProvider(
        ServiceAuthConfig(
            enabled=True,
            provider="cognito",
            issuer="https://issuer",
            jwks_url="https://issuer/.well-known/jwks.json",
            audience="client-id",
            required_scopes=["automa:invoke"],
        ),
        ServiceIdentityConfig(),
        jwk_client=FakeJWKClient(),
    )

    principal = provider.authenticate("Bearer token")

    assert principal.user_id == "subject"
    assert principal.scopes == ["automa:invoke"]
    assert decode_kwargs["options"] == {"verify_aud": False}
    assert "audience" not in decode_kwargs


def test_cognito_access_token_rejects_wrong_client_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_decode(token, signing_key, **kwargs):
        return {
            "sub": "subject",
            "token_use": "access",
            "client_id": "wrong-client",
            "scope": "automa:invoke",
        }

    import jwt

    monkeypatch.setattr(jwt, "decode", fake_decode)
    provider = CognitoAuthProvider(
        ServiceAuthConfig(
            enabled=True,
            provider="cognito",
            issuer="https://issuer",
            jwks_url="https://issuer/.well-known/jwks.json",
            audience="client-id",
        ),
        ServiceIdentityConfig(),
        jwk_client=FakeJWKClient(),
    )

    with pytest.raises(AuthError, match="client_id"):
        provider.authenticate("Bearer token")


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
        return JSONResponse(getattr(request.state, PRINCIPAL_STATE_KEY).to_metadata())

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


def test_auth_middleware_allows_public_paths_with_trailing_slash() -> None:
    async def endpoint(request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/health/", endpoint)])
    app.add_middleware(
        AuthMiddleware,
        auth_provider=StaticAuthProvider(
            error=AuthError("Missing Authorization header.", status_code=401)
        ),
        public_paths=["/health"],
    )

    response = TestClient(app).get("/health/")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_context_builder_copies_principal_from_request_state() -> None:
    request = Mock()
    request.headers = Headers({})
    request.scope = {}
    request.state = Mock()
    setattr(
        request.state,
        PRINCIPAL_STATE_KEY,
        Principal(
            subject="sub",
            user_id="user",
            tenant_id="tenant",
        ),
    )

    context = AutomaServerCallContextBuilder().build(request)

    assert context.state[PRINCIPAL_STATE_KEY].user_id == "user"
    assert context.state[IDENTITY_METADATA_STATE_KEY]["auth.trusted"] is True
    assert context.tenant == "tenant"


def test_service_config_defaults_to_disabled_auth() -> None:
    config = ServiceConfig.from_value(None)

    assert config.auth.enabled is False
