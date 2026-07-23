from __future__ import annotations

import pytest
from google.protobuf.json_format import ParseDict

from a2a.types import AgentCard
from automa_ai.agents.remote_agent import RemoteAgent
from automa_ai.config.a2a_auth import A2AClientAuthConfig
from automa_ai.config.agent_spec import SubAgentYamlSpec, YamlAgentSpec


def _remote_card() -> dict:
    return {
        "name": "Remote CE Expert",
        "description": "A remote A2A agent protected by an API key.",
        "version": "1.0.0",
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "capabilities": {"streaming": True},
        "supportedInterfaces": [
            {
                "url": "https://example.com/ce-expert/invoke/",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "securitySchemes": {
            "permitce_api_key": {
                "apiKeySecurityScheme": {
                    "location": "header",
                    "name": "x-api-key",
                }
            }
        },
    }


def test_api_key_auth_uses_header_declared_by_agent_card() -> None:
    auth = A2AClientAuthConfig(
        scheme="permitce_api_key",
        api_key="test-api-key",
    )

    assert auth.request_headers(_remote_card()) == {"x-api-key": "test-api-key"}


def test_api_key_auth_normalizes_card_header_name() -> None:
    card = _remote_card()
    card["securitySchemes"]["permitce_api_key"]["apiKeySecurityScheme"][
        "name"
    ] = " x-api-key "

    assert A2AClientAuthConfig(
        scheme="permitce_api_key",
        api_key="test-api-key",
    ).request_headers(card) == {"x-api-key": "test-api-key"}


def test_api_key_auth_rejects_card_without_matching_scheme() -> None:
    auth = A2AClientAuthConfig(
        scheme="permitce_api_key",
        api_key="test-api-key",
    )
    card = _remote_card()
    card["securitySchemes"] = {}

    with pytest.raises(ValueError, match="does not declare security scheme"):
        auth.request_headers(card)


@pytest.mark.parametrize(
    ("header_name", "api_key", "match"),
    [
        ("x-api-key\r\nx-injected: value", "test-api-key", "invalid header name"),
        ("x api-key", "test-api-key", "invalid header name"),
        ("x-api-key:", "test-api-key", "invalid header name"),
        ("x-api-key", "test-api-key\r\nx-injected: value", "must not contain"),
    ],
)
def test_api_key_auth_rejects_header_injection_values(
    header_name: str,
    api_key: str,
    match: str,
) -> None:
    card = _remote_card()
    card["securitySchemes"]["permitce_api_key"]["apiKeySecurityScheme"][
        "name"
    ] = header_name

    with pytest.raises(ValueError, match=match):
        A2AClientAuthConfig(
            scheme="permitce_api_key",
            api_key=api_key,
        ).request_headers(card)


@pytest.mark.asyncio
async def test_remote_agent_passes_configured_headers_through_a2a_context() -> None:
    agent = RemoteAgent(
        agent_name="remote_ce_expert",
        subagent_card=ParseDict(_remote_card(), AgentCard()),
        description="Remote CE expert.",
        request_headers={"x-api-key": "test-api-key"},
    )
    try:
        context = agent._request_context()
        assert context is not None
        assert context.service_parameters == {"x-api-key": "test-api-key"}
    finally:
        await agent.close()


def test_yaml_subagent_resolves_api_key_auth_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CE_EXPERT_API_KEY", "test-api-key")
    spec = YamlAgentSpec.from_yaml_text(
        """
spec_version: v1
agent_card:
  name: Coordinator
  description: Coordinates remote agents.
  version: 1.0.0
  defaultInputModes: [text]
  defaultOutputModes: [text]
  capabilities: {streaming: true}
  supportedInterfaces:
    - url: http://localhost:32123
      protocolBinding: JSONRPC
      protocolVersion: "1.0"
instructions: {text: Coordinate the request.}
model: {provider: ollama, name: llama3.1:8b}
subagents:
  - agent_card:
      name: CE Expert
      description: Remote CE analysis.
      version: 1.0.0
      defaultInputModes: [text]
      defaultOutputModes: [text]
      capabilities: {streaming: true}
      supportedInterfaces:
        - url: https://example.com/ce-expert/invoke/
          protocolBinding: JSONRPC
          protocolVersion: "1.0"
      securitySchemes:
        permitce_api_key:
          apiKeySecurityScheme:
            location: header
            name: x-api-key
    auth:
      type: api_key
      scheme: permitce_api_key
      api_key: ${CE_EXPERT_API_KEY}
"""
    )

    subagent = spec.to_factory_kwargs()["subagent_config"][0]

    assert subagent.request_headers == {"x-api-key": "test-api-key"}


def test_yaml_subagent_resolves_custom_request_headers_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CE_EXPERT_API_KEY", "test-api-key")
    spec = YamlAgentSpec.from_yaml_text(
        """
spec_version: v1
agent_card:
  name: Coordinator
  description: Coordinates remote agents.
  version: 1.0.0
  defaultInputModes: [text]
  defaultOutputModes: [text]
  capabilities: {streaming: true}
  supportedInterfaces:
    - url: http://localhost:32123
      protocolBinding: JSONRPC
      protocolVersion: "1.0"
instructions: {text: Coordinate the request.}
model: {provider: ollama, name: llama3.1:8b}
subagents:
  - agent_card:
      name: CE Expert
      description: Remote CE analysis.
      version: 1.0.0
      defaultInputModes: [text]
      defaultOutputModes: [text]
      capabilities: {streaming: true}
      supportedInterfaces:
        - url: https://example.com/ce-expert/invoke/
          protocolBinding: JSONRPC
          protocolVersion: "1.0"
    request_headers:
      x-api-key: ${CE_EXPERT_API_KEY}
      x-gateway-client: ce-backend
"""
    )

    subagent = spec.to_factory_kwargs()["subagent_config"][0]

    assert subagent.request_headers == {
        "x-api-key": "test-api-key",
        "x-gateway-client": "ce-backend",
    }


def test_yaml_subagent_normalizes_custom_request_header_names() -> None:
    subagent = SubAgentYamlSpec(
        agent_card=_remote_card(),
        request_headers={" x-api-key ": "test-api-key"},
    )

    assert subagent.resolve_request_headers(_remote_card()) == {
        "x-api-key": "test-api-key"
    }


@pytest.mark.parametrize("header_name", ["x api-key", "x-api-key:"])
def test_yaml_subagent_rejects_invalid_custom_request_header_name(
    header_name: str,
) -> None:
    subagent = SubAgentYamlSpec(
        agent_card=_remote_card(),
        request_headers={header_name: "test-api-key"},
    )

    with pytest.raises(ValueError, match="invalid header name"):
        subagent.resolve_request_headers(_remote_card())


def test_yaml_subagent_rejects_auth_and_custom_request_headers() -> None:
    with pytest.raises(ValueError, match="either auth or request_headers"):
        YamlAgentSpec.from_yaml_text(
            """
spec_version: v1
agent_card:
  name: Coordinator
  description: Coordinates remote agents.
  version: 1.0.0
  defaultInputModes: [text]
  defaultOutputModes: [text]
  capabilities: {streaming: true}
  supportedInterfaces:
    - url: http://localhost:32123
      protocolBinding: JSONRPC
      protocolVersion: "1.0"
instructions: {text: Coordinate the request.}
model: {provider: ollama, name: llama3.1:8b}
subagents:
  - agent_card:
      name: CE Expert
      description: Remote CE analysis.
      version: 1.0.0
      defaultInputModes: [text]
      defaultOutputModes: [text]
      capabilities: {streaming: true}
      supportedInterfaces:
        - url: https://example.com/ce-expert/invoke/
          protocolBinding: JSONRPC
          protocolVersion: "1.0"
      securitySchemes:
        permitce_api_key:
          apiKeySecurityScheme:
            location: header
            name: x-api-key
    auth:
      scheme: permitce_api_key
      api_key: test-api-key
    request_headers:
      x-api-key: test-api-key
"""
        )


def test_custom_request_headers_reject_header_injection_value() -> None:
    spec = YamlAgentSpec.from_yaml_text(
        """
spec_version: v1
agent_card:
  name: Coordinator
  description: Coordinates remote agents.
  version: 1.0.0
  defaultInputModes: [text]
  defaultOutputModes: [text]
  capabilities: {streaming: true}
  supportedInterfaces:
    - url: http://localhost:32123
      protocolBinding: JSONRPC
      protocolVersion: "1.0"
instructions: {text: Coordinate the request.}
model: {provider: ollama, name: llama3.1:8b}
subagents:
  - agent_card:
      name: CE Expert
      description: Remote CE analysis.
      version: 1.0.0
      defaultInputModes: [text]
      defaultOutputModes: [text]
      capabilities: {streaming: true}
      supportedInterfaces:
        - url: https://example.com/ce-expert/invoke/
          protocolBinding: JSONRPC
          protocolVersion: "1.0"
    request_headers:
      x-api-key: "test-api-key\\r\\nx-injected: value"
"""
    )

    with pytest.raises(ValueError, match="invalid header value"):
        spec.to_factory_kwargs()
