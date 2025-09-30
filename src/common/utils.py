import socket
import time

from common.mcp_registry import MCPServerConfig
from src.common.types import ServerConfig

# Map MCPConfigServer to ServerConfig
def map_mcp_config_to_server_config(mcp_config: MCPServerConfig) -> ServerConfig:
    """
    Map MCP configuration data to server data
    :param mcp_config:
    :return:
    """
    return ServerConfig(
        host=mcp_config.host,
        port=mcp_config.port,
        transport=mcp_config.transport,
        url=map_to_url(mcp_config.host, mcp_config.port)
    )

def map_to_url(hostname, port, protocol="http"):
    """
    Map hostname and port to a URL format.

    :param hostname: Hostname (e.g., "example.com").
    :param port: Port number (e.g., 8080).
    :param protocol: Protocol for the URL (default is "http").
    :return: URL as a string.
    """
    if not hostname or not port:
        raise ValueError("Invalid hostname or port provided.")

    # Construct the URL
    url = f"{protocol}://{hostname}:{port}"

    return url


def wait_for_port(host, port, timeout=15):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    raise TimeoutError(f"Timeout waiting for port {host}:{port}")


def get_agent_mcp_server_config() -> ServerConfig:
    """Get the MCP server configuration."""
    return ServerConfig(
        host="localhost",
        port=10100,  # needs to update when mcp server is up.
        transport="sse",
        url="http://localhost:10100/sse",  # needs to update when mcp server is up.
    )


def get_os_model_mcp_server_config() -> ServerConfig:
    """Get the MCP server configuration."""
    return ServerConfig(
        host="localhost",
        port=10200,  # needs to update when mcp server is up.
        transport="sse",
        url="http://localhost:10200/sse",  # needs to update when mcp server is up.
    )


def get_os_geo_mcp_server_config() -> ServerConfig:
    """Get the MCP server configuration."""
    return ServerConfig(
        host="localhost",
        port=10201,  # needs to update when mcp server is up.
        transport="sse",
        url="http://localhost:10201/sse",  # needs to update when mcp server is up.
    )
