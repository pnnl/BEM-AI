import logging
import os
import sys

from mcp.server.mcpserver import MCPServer

logger = logging.getLogger(__name__)

MCP_NAME = "chat_mcp"

# counties_data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'resources', 'counties.dat')

def serve(host, port, transport):
    """Initialize and runs the agent cards mcp_servers server.
    Args:
        host: The hostname or IP address to bind the server to.
        port: The port number to bind the server to.
        transport: The transport mechanism for the MCP server (e.g., 'stdio', 'sse')

    Raises:
        ValueError
    """
    logger.info("Starting MCP Model Server")
    mcp = MCPServer(MCP_NAME)

    @mcp.tool(
        name="get_weather_by_city_and_state",
        description="Get current weather condition by city and state"
    )
    def get_weather_by_city(city: str, state: str) -> str:
        """
        Get the current weather condition by city and state
        :param city: name of the city, For example: "Boulder"
        :param state: name of the State, For example: "Colorado"
        :return: weather condition: Sunny | Windy | Cloudy
        """
        if city.lower() == "tampa" and state.lower() == "florida":
            return "Sunny"
        return "Cloudy"

    logger.info(f"MCP Server at {host}:{port} and transport {transport}")
    mcp.run(transport=transport, host=host, port=port)
