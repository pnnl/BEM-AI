"""Outbound authentication configuration for remote A2A agents."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class A2AClientAuthConfig(BaseModel):
    """Credentials an AUTOMA-AI client uses to call one remote A2A agent.

    Credentials are intentionally configured separately from the Agent Card:
    the card declares the authentication requirement, while deployments supply
    the secret through environment-variable resolution or another secret store.
    """

    type: Literal["api_key"] = "api_key"
    scheme: str = Field(min_length=1)
    api_key: SecretStr

    model_config = ConfigDict(extra="forbid")

    def request_headers(self, agent_card: dict[str, Any]) -> dict[str, str]:
        """Validate the card requirement and return the credential header."""
        security_schemes = agent_card.get("securitySchemes")
        if not isinstance(security_schemes, dict):
            raise ValueError(
                "Remote A2A agent card must declare securitySchemes when "
                "subagent auth is configured."
            )

        declared_scheme = security_schemes.get(self.scheme)
        if not isinstance(declared_scheme, dict):
            raise ValueError(
                f"Remote A2A agent card does not declare security scheme "
                f"'{self.scheme}'."
            )

        api_key_scheme = declared_scheme.get("apiKeySecurityScheme")
        if not isinstance(api_key_scheme, dict):
            raise ValueError(
                f"A2A security scheme '{self.scheme}' is not an API-key scheme."
            )

        if api_key_scheme.get("location") != "header":
            raise ValueError(
                f"A2A API-key scheme '{self.scheme}' must use location 'header'."
            )

        header_name = api_key_scheme.get("name")
        if not isinstance(header_name, str) or not header_name.strip():
            raise ValueError(
                f"A2A API-key scheme '{self.scheme}' must declare a header name."
            )

        return {header_name: self.api_key.get_secret_value()}
