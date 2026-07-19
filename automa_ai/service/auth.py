from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from automa_ai.config.service import ServiceAuthConfig, ServiceIdentityConfig
from automa_ai.service.identity import Principal


class AuthError(Exception):
    """Raised when request authentication or authorization fails."""

    def __init__(self, message: str, *, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


class AuthProvider(ABC):
    """Service-boundary authentication provider."""

    @abstractmethod
    def authenticate(self, authorization: str | None) -> Principal:
        raise NotImplementedError


class DisabledAuthProvider(AuthProvider):
    def authenticate(self, authorization: str | None) -> Principal:
        raise AuthError("Authentication is disabled.", status_code=401)


class JWTAuthProvider(AuthProvider):
    """JWT bearer-token verifier backed by a JWKS endpoint."""

    def __init__(
        self,
        auth_config: ServiceAuthConfig,
        identity_config: ServiceIdentityConfig,
        *,
        jwk_client: Any | None = None,
    ) -> None:
        self.auth_config = auth_config
        self.identity_config = identity_config
        if jwk_client is not None:
            self.jwk_client = jwk_client
        else:
            import jwt

            self.jwk_client = jwt.PyJWKClient(auth_config.resolved_jwks_url)

    def authenticate(self, authorization: str | None) -> Principal:
        token = _extract_bearer_token(authorization)
        claims = self._decode_token(token)
        principal = principal_from_claims(claims, self.identity_config)
        _require_any(
            actual=principal.scopes,
            required=self.auth_config.required_scopes,
            label="scope",
        )
        _require_any(
            actual=principal.groups,
            required=self.auth_config.required_groups,
            label="group",
        )
        return principal

    def _decode_token(self, token: str) -> dict[str, Any]:
        import jwt
        from jwt import InvalidTokenError

        try:
            signing_key = self.jwk_client.get_signing_key_from_jwt(token).key
            return jwt.decode(
                token,
                signing_key,
                algorithms=self.auth_config.algorithms,
                audience=self.auth_config.audience,
                issuer=self.auth_config.resolved_issuer,
                leeway=self.auth_config.leeway_seconds,
            )
        except InvalidTokenError as exc:
            raise AuthError("Invalid bearer token.", status_code=401) from exc
        except Exception as exc:
            raise AuthError("Unable to verify bearer token.", status_code=401) from exc


class CognitoAuthProvider(JWTAuthProvider):
    """AWS Cognito JWT verifier using Cognito issuer and JWKS conventions."""

    def _decode_token(self, token: str) -> dict[str, Any]:
        import jwt
        from jwt import InvalidTokenError

        try:
            signing_key = self.jwk_client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=self.auth_config.algorithms,
                issuer=self.auth_config.resolved_issuer,
                leeway=self.auth_config.leeway_seconds,
                options={"verify_aud": False},
            )
        except InvalidTokenError as exc:
            raise AuthError("Invalid bearer token.", status_code=401) from exc
        except Exception as exc:
            raise AuthError("Unable to verify bearer token.", status_code=401) from exc

        self._validate_app_client(claims)
        return claims

    def _validate_app_client(self, claims: dict[str, Any]) -> None:
        expected = self.auth_config.audience
        if expected is None:
            return
        token_use = claims.get("token_use")
        if token_use == "access":
            actual = claims.get("client_id")
            label = "client_id"
        elif token_use == "id":
            actual = claims.get("aud")
            label = "aud"
        else:
            raise AuthError(
                "Cognito token is missing required token_use claim.",
                status_code=403,
            )
        if not _claim_matches_expected(actual, expected):
            raise AuthError(
                f"Cognito token {label} does not match configured audience.",
                status_code=403,
            )


def build_auth_provider(
    auth_config: ServiceAuthConfig,
    identity_config: ServiceIdentityConfig,
) -> AuthProvider | None:
    if not auth_config.enabled:
        return None
    if auth_config.provider == "cognito":
        return CognitoAuthProvider(auth_config, identity_config)
    return JWTAuthProvider(auth_config, identity_config)


def principal_from_claims(
    claims: dict[str, Any],
    identity_config: ServiceIdentityConfig,
) -> Principal:
    subject = _claim_as_str(claims, "sub")
    user_id = _claim_as_str(claims, identity_config.user_id_claim)
    tenant_id = (
        _claim_as_optional_str(claims, identity_config.tenant_id_claim)
        if identity_config.tenant_id_claim
        else None
    )
    groups = _claim_as_list(claims.get(identity_config.groups_claim))
    scopes = _claim_as_list(claims.get(identity_config.scopes_claim))
    return Principal(
        subject=subject,
        user_id=user_id,
        tenant_id=tenant_id,
        groups=groups,
        scopes=scopes,
        claims=dict(claims),
    )


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise AuthError("Missing Authorization header.", status_code=401)
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("Authorization header must use Bearer token.", status_code=401)
    return token.strip()


def _claim_as_str(claims: dict[str, Any], name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value:
        raise AuthError(f"Token is missing required claim '{name}'.", status_code=403)
    return value


def _claim_as_optional_str(claims: dict[str, Any], name: str | None) -> str | None:
    if not name:
        return None
    value = claims.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise AuthError(
            f"Token claim '{name}' must be a non-empty string.", status_code=403
        )
    return value


def _claim_as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item for item in value.split() if item]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _claim_matches_expected(actual: Any, expected: str | list[str]) -> bool:
    expected_values = {expected} if isinstance(expected, str) else set(expected)
    if isinstance(actual, str):
        return actual in expected_values
    if isinstance(actual, list):
        return any(item in expected_values for item in actual if isinstance(item, str))
    return False


def _require_any(*, actual: list[str], required: list[str], label: str) -> None:
    if not required:
        return
    if not set(actual).intersection(required):
        raise AuthError(f"Token lacks required {label}.", status_code=403)
