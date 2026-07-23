from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from a2a.auth.user import User
from a2a.server.context import ServerCallContext
from a2a.server.routes.common import DefaultServerCallContextBuilder

from automa_ai.service.auth import AuthError, AuthProvider
from automa_ai.service.constants import IDENTITY_METADATA_STATE_KEY, PRINCIPAL_STATE_KEY
from automa_ai.service.identity import Principal


class PrincipalUser(User):
    """Expose a verified principal through the A2A task ownership interface."""

    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def user_name(self) -> str:
        if self.principal.tenant_id:
            return f"{self.principal.tenant_id}:{self.principal.user_id}"
        return self.principal.user_id


class AuthMiddleware(BaseHTTPMiddleware):
    """Authenticate requests and attach a trusted principal to request state."""

    def __init__(
        self,
        app,
        auth_provider: AuthProvider | None,
        public_paths: list[str] | None = None,
    ):
        super().__init__(app)
        self.auth_provider = auth_provider
        self.public_paths = {path.rstrip("/") or "/" for path in (public_paths or [])}

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path.rstrip("/") or "/"
        if self.auth_provider is None or path in self.public_paths:
            return await call_next(request)
        try:
            principal = self.auth_provider.authenticate(
                request.headers.get("authorization")
            )
        except AuthError as exc:
            return JSONResponse(
                {
                    "error": "unauthorized" if exc.status_code == 401 else "forbidden",
                    "message": str(exc),
                },
                status_code=exc.status_code,
            )
        setattr(request.state, PRINCIPAL_STATE_KEY, principal)
        return await call_next(request)


class AutomaServerCallContextBuilder(DefaultServerCallContextBuilder):
    """Copy trusted service identity from Starlette state into A2A call context."""

    def build(self, request: Request) -> ServerCallContext:
        context = super().build(request)
        principal = getattr(request.state, PRINCIPAL_STATE_KEY, None)
        if isinstance(principal, Principal):
            context.user = PrincipalUser(principal)
            context.state[PRINCIPAL_STATE_KEY] = principal
            context.state[IDENTITY_METADATA_STATE_KEY] = principal.to_metadata()
            if principal.tenant_id:
                context.tenant = principal.tenant_id
        return context
