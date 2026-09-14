import socket
import time
import warnings
from functools import wraps
from typing import Any

from automa_ai.common.mcp_registry import MCPServerConfig
from automa_ai.common.types import ServerConfig
from automa_ai.memory.memory_stores import MemoryStoreRegistry
from automa_ai.token_management.store import TokenUsageStoreRegistry
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


def load_token_usage_store_plugins():
    for ep in _iter_entry_points("automa_ai.token_usage_stores"):
        store_cls = ep.load()
        TokenUsageStoreRegistry.register(ep.name, store_cls)


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
        url=map_to_url(mcp_config.host, mcp_config.port),
        timeout=mcp_config.timeout,
        sse_read_timeout=mcp_config.sse_read_timeout,
    )


def map_server_config_to_mcp_connection(server_config: ServerConfig) -> dict:
    """Map an HTTP MCP server into the standard FastMCP connection shape."""
    if server_config.transport == "stdio":
        raise ValueError(
            "MCP stdio connections require a command and arguments, which "
            "MCPServerConfig does not model. Use streamable-http or SSE."
        )
    return {
        "url": f"{server_config.url}/sse"
        if server_config.transport == "sse"
        else f"{server_config.url}/mcp",
    }


def _mcp_adapter_targets(server_configs: dict[str, ServerConfig]) -> list[object]:
    """Build native LangChain MCPAdapter targets from AUTOMA-AI server configs.

    FastMCP clients are used for both HTTP transports so configured timeouts are
    honored. SSE remains a compatibility path because FastMCP no longer infers
    its deprecated transport from a URL.
    """
    from fastmcp import Client
    from fastmcp.client.transports import SSETransport, StreamableHttpTransport

    targets: list[object] = []

    for name, server_config in server_configs.items():
        connection = map_server_config_to_mcp_connection(server_config)
        if server_config.transport == "sse":
            transport = SSETransport(
                connection["url"],
                sse_read_timeout=server_config.sse_read_timeout,
            )
            targets.append(Client(transport, timeout=server_config.timeout))
        else:
            transport = StreamableHttpTransport(connection["url"])
            targets.append(Client(transport, timeout=server_config.timeout))
    return targets


class MCPToolSession(list):
    """List-compatible MCP tools that own their entered adapter contexts."""

    def __init__(self) -> None:
        super().__init__()
        self._adapters: list[Any] = []
        self._closed = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        for adapter in reversed(self._adapters):
            await adapter.__aexit__(None, None, None)
        self._adapters.clear()


async def load_mcp_tools(server_configs: dict[str, ServerConfig]) -> MCPToolSession:
    """Discover tools and retain MCP adapters until the caller closes them."""
    try:
        from langchain.mcp import MCPAdapter
    except ImportError as exc:
        raise ImportError(
            "MCP tool integration requires the optional 'mcp' extra. "
            "Install it with `pip install automa-ai[mcp]`."
        ) from exc

    tools = MCPToolSession()
    try:
        for target in _mcp_adapter_targets(server_configs):
            adapter = MCPAdapter(target)
            await adapter.__aenter__()
            tools._adapters.append(adapter)
            tools.extend(await adapter.list_tools())
    except BaseException:
        await tools.aclose()
        raise
    return tools


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
                    stacklevel=2,
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
