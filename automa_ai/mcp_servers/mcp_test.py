import json
import time
from multiprocessing import Process

import pytest
from mcp import ClientSession
from mcp.client.sse import sse_client

from automa_ai.mcp_servers.server import serve

MCP_HOST = "localhost"
MCP_PORT = 10100
MCP_URL = f"http://{MCP_HOST}:{MCP_PORT}/sse"


@pytest.fixture(scope="session", autouse=True)
def start_mcp_server():
    """Start MCP server in a subprocess for integration testing."""
    process = Process(target=serve, args=(MCP_HOST, MCP_PORT, "sse"), daemon=True)
    process.start()
    time.sleep(5)  # give time for server to boot and load vectorstore
    yield
    process.terminate()


@pytest.mark.asyncio
async def test_call_find_agent():
    async with sse_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                name="find_agent", arguments={"query": "change geometry"}
            )
            assert result.content and isinstance(result.content[0].text, str)

            card = json.loads(result.content[0].text)
            assert card["name"] == "Energy Model Geometry Agent"


@pytest.mark.asyncio
async def test_read_agent_resource():
    async with sse_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.read_resource(
                uri="resource://agent_cards/geometry_agent"
            )
            # NOTE: resource return is contents, not content.
            assert result.contents and isinstance(result.contents[0].text, str)
            card = json.loads(result.contents[0].text)
            assert "agent_card" in card
            assert card["agent_card"]["name"] == "Energy Model Geometry Agent"
