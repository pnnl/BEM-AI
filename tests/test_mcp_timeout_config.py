from automa_ai.common.mcp_registry import MCPServerConfig
from automa_ai.common.utils import (
    map_mcp_config_to_server_config,
    map_server_config_to_mcp_connection,
)


def test_mcp_timeouts_propagate_to_server_config() -> None:
    config = MCPServerConfig(
        name="ipac",
        host="localhost",
        port=11000,
        serve=lambda *args: None,
        transport="sse",
        timeout=30,
        sse_read_timeout=300,
    )

    server_config = map_mcp_config_to_server_config(config)

    assert server_config.timeout == 30
    assert server_config.sse_read_timeout == 300


def test_mcp_sse_connection_maps_to_legacy_sse_url() -> None:
    config = MCPServerConfig(
        name="ipac",
        host="localhost",
        port=11000,
        serve=lambda *args: None,
        transport="sse",
        timeout=30,
        sse_read_timeout=300,
    )

    server_config = map_mcp_config_to_server_config(config)
    connection = map_server_config_to_mcp_connection(server_config)

    assert connection == {
        "url": "http://localhost:11000/sse",
    }


def test_mcp_stdio_connection_requires_command_configuration() -> None:
    config = MCPServerConfig(
        name="local",
        host="localhost",
        port=11000,
        serve=lambda *args: None,
        transport="stdio",
        timeout=30,
        sse_read_timeout=300,
    )

    server_config = map_mcp_config_to_server_config(config)
    with pytest.raises(ValueError, match="require a command"):
        map_server_config_to_mcp_connection(server_config)


def test_mcp_streamable_http_connection_maps_to_mcp_endpoint() -> None:
    config = MCPServerConfig(
        name="modern",
        host="localhost",
        port=11000,
        serve=lambda *args: None,
        transport="streamable-http",
    )

    server_config = map_mcp_config_to_server_config(config)

    assert map_server_config_to_mcp_connection(server_config) == {
        "url": "http://localhost:11000/mcp",
    }
import pytest
