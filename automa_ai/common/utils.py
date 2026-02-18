import socket
import time
import warnings
from functools import wraps

from automa_ai.common.mcp_registry import MCPServerConfig
from automa_ai.common.types import ServerConfig
from automa_ai.memory.memory_stores import MemoryStoreRegistry
from automa_ai.tools.registry import DEFAULT_TOOL_REGISTRY

import importlib.metadata


def _iter_entry_points(group: str):
    eps = importlib.metadata.entry_points()
    if hasattr(eps, "select"):
        return eps.select(group=group)
    return eps.get(group, [])


def load_memory_store_plugins():
    for ep in _iter_entry_points("automa_ai.memory_stores"):
        store_cls = ep.load()
        MemoryStoreRegistry.register(ep.name, store_cls)


def load_tool_plugins():
    for ep in _iter_entry_points("automa_ai.tools"):
        builder = ep.load()
        try:
            DEFAULT_TOOL_REGISTRY.register(ep.name, builder)
        except ValueError:
            # Plugin may already be loaded in this process.
            pass


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


def deprecated(message: str):
    def decorator(obj):
        if isinstance(obj, type):
            # It's a class
            orig_init = obj.__init__

            @wraps(orig_init)
            def new_init(self, *args, **kwargs):
                warnings.warn(
                    f"{obj.__name__} is deprecated: {message}",
                    DeprecationWarning,
                    stacklevel=2
                )
                return orig_init(self, *args, **kwargs)

            obj.__init__ = new_init
            return obj

        else:
            # It's a function
            @wraps(obj)
            def wrapper(*args, **kwargs):
                warnings.warn(
                    f"{obj.__name__} is deprecated: {message}",
                    DeprecationWarning,
                    stacklevel=2,
                )
                return obj(*args, **kwargs)

            return wrapper

    return decorator
