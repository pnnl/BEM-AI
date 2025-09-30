import asyncio
import json
import logging
from contextlib import asynccontextmanager

import click
from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.client.sse import sse_client
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.types import CallToolResult, ReadResourceResult

logging.basicConfig(
    filename="mcp_client.log",
    filemode="w",  # Overwrite each run
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = get_logger(__name__)


@asynccontextmanager
async def init_session(host, port, transport):
    """Initializes and manages an MCP ClientSession based on the specified transport.

    This asynchronous context manager establishes a connection to an MCP server
    using either Server-Sent Events (SSE) or Standard I/O (STDIO) transport.
    It handles the setup and teardown of the connection and yields an active
    `ClientSession` object ready for communication.

    Args:
        host: The hostname or IP address of the MCP server (used for SSE).
        port: The port number of the MCP server (used for SSE).
        transport: The communication transport to use ('sse' or 'stdio').

    Yields:
        ClientSession: An initialized and ready-to-use MCP client session.

    Raises:
        ValueError: If an unsupported transport type is provided (implicitly,
                    as it won't match 'sse' or 'stdio').
        Exception: Other potential exceptions during client initialization or
                   session setup.
    """
    if transport == "sse":
        url = f"http://{host}:{port}/sse"
        async with sse_client(url) as (read_stream, write_stream):
            async with ClientSession(
                read_stream=read_stream, write_stream=write_stream
            ) as session:
                logger.debug("SSE ClientSession created, initializing...")
                await session.initialize()
                logger.info("SSE ClientSession initialized successfully...")
                yield session
    elif transport == "stdio":
        stdio_params = StdioServerParameters(
            command="uv",
            args=["run", "eplus-doc-mcp"],
        )
        async with stdio_client(stdio_params) as (read_stream, write_stream):
            async with ClientSession(
                read_stream=read_stream,
                write_stream=write_stream,
            ) as session:
                logger.debug("STDIO ClientSession created, initializing...")
                await session.initialize()
                logger.info("STDIO ClientSession initialized successfully.")
                yield session
    else:
        logger.error(f"Unsupported transport type: {transport}")
        raise ValueError(
            f"Unsupported transport type: {transport}. Must be 'sse' or 'stdio'."
        )


async def search_energyplus_docs(session: ClientSession, query) -> CallToolResult:
    """Calls the 'search_energyplus_docs' tool on the connected MCP server.

    Args:
        session: The active ClientSession,
        query: The natural language query to send to the 'find_agent' tool.

    Returns:
        The result of the tool call.
    """
    logger.info(f"Calling 'search_energyplus_docs' tool with query: '{query[:50]}'")
    return await session.call_tool(
        name="search_energyplus_docs",
        arguments={
            "query": query,
            "max_results": 50
        },
    )

async def get_page_details(session: ClientSession, query) -> CallToolResult:
    """Calls the 'search_energyplus_docs' tool on the connected MCP server.

    Args:
        session: The active ClientSession,
        query: The natural language query to send to the 'find_agent' tool.

    Returns:
        The result of the tool call.
    """
    logger.info(f"Calling 'get_page_details' tool with query: '{query[:50]}'")
    return await session.call_tool(
        name="get_page_details",
        arguments={
            "url": query,
        },
    )

async def discover_documentation_structure(session: ClientSession, query) -> CallToolResult:
    """Calls the 'search_energyplus_docs' tool on the connected MCP server.

    Args:
        session: The active ClientSession,
        query: The natural language query to send to the 'find_agent' tool.

    Returns:
        The result of the tool call.
    """
    logger.info(f"Calling 'discover_documentation_structure' tool with query: '{query[:50]}'")
    return await session.call_tool(
        name="get_page_details",
        arguments={
            "max_pages": 100,
        },
    )


# Test util
async def main(host, port, transport, search_energyplus_docs, get_page_details, discover_documentation_structure):
    """Main asynchronous function to connect to the MCP server and execute commands.

    Used for local testing.

    Args:
        host: Server hostname.
        port: Server port.
        transport: Connection transport ('sse' or 'stdio').
        query: Optional query string for the 'find_agent' tool.
        resource: Optional resource URI to read.
    """
    logger.info("Starting Client to connect to MCP")
    async with init_session(host, port, transport) as session:
        if search_energyplus_docs:
            result = await search_energyplus_docs(session, search_energyplus_docs)
            data = json.loads(result.content[0].text)
            logger.info(json.dumps(data, indent=2))
        if get_page_details:
            result = await get_page_details(session, get_page_details)
            logger.info(result)
            data = json.loads(result.contents[0].text)
            logger.info(json.dumps(data, indent=2))
        if discover_documentation_structure:
            result = await discover_documentation_structure(session, discover_documentation_structure)
            logger.info(result)
            data = json.loads(result.contents[0].text)
            logger.info(json.dumps(data, indent=2))


# Command line tester
@click.command()
@click.option("--host", default="localhost", help="SSE Host")
@click.option("--port", default="10100", help="SSE Port")
@click.option("--transport", default="stdio", help="MCP Transport")
@click.option("--search_energyplus_docs", help="Search through EnergyPlus Input/Output Reference documentation with intelligent ranking")
@click.option("--get_page_details", help="Get comprehensive information about a specific EnergyPlus documentation page")
@click.option("--discover_documentation_structure", help="Discover and map the structure of the EnergyPlus documentation site")
def cli(host, port, transport, search_energyplus_docs, get_page_details, discover_documentation_structure):
    """A command-line client to interact with the Agent Cards MCP server."""
    search_energyplus_docs = "Find out the information about sizing zones"
    asyncio.run(main(host, port, transport, search_energyplus_docs, get_page_details, discover_documentation_structure))


if __name__ == "__main__":
    cli()
