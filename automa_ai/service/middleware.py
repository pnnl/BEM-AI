from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from a2a.server.context import ServerCallContext
from a2a.server.routes.common import DefaultServerCallContextBuilder

from automa_ai.service.auth import AuthError, AuthProvider
from automa_ai.service.identity import Principal


PRINCIPAL_STATE_KEY = "automa_principal"


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
        self.public_paths = set(public_paths or [])

    async def dispatch(self, request: Request, call_next) -> Response:
        if self.auth_provider is None or request.url.path in self.public_paths:
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
        request.state.automa_principal = principal
        return await call_next(request)


class AutomaServerCallContextBuilder(DefaultServerCallContextBuilder):
    """Copy trusted service identity from Starlette state into A2A call context."""

    def build(self, request: Request) -> ServerCallContext:
        context = super().build(request)
        principal = getattr(request.state, "automa_principal", None)
        if isinstance(principal, Principal):
            context.state[PRINCIPAL_STATE_KEY] = principal
            context.state["automa_identity"] = principal.to_metadata()
            context.tenant = principal.tenant_id or ""
        return context
