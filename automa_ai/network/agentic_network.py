import asyncio
import logging
from typing import Dict, Any

from automa_ai.common.agent_registry import A2AServerManager, A2AAgentServer
from automa_ai.common.base_agent import BaseAgent
from automa_ai.common.file_util import verify_directory_and_json_files
from automa_ai.common.mcp_registry import MCPServerManager, MCPServerConfig
from automa_ai.mcp_servers.server import serve

logger = logging.getLogger(__name__)


class ServiceOrchestrator:
    def __init__(self, orchestrator: BaseAgent, agent_cards_dir: str):
        """
        :param orchestrator: orchestrator agent
        :param agent_cards_dir: directory to agent cards.
        """
        self.mcp_manager = MCPServerManager()
        self.a2a_manager = A2AServerManager()
        self.orchestrator = orchestrator
        # Check agent_card_validity

        assert verify_directory_and_json_files(agent_cards_dir), "Invalid or empty directory"

        agent_card_mcp_config = MCPServerConfig(
            name="a2a-agent-cards",
            host="localhost",
            port=10100,
            serve=serve,
            transport="sse",
            agent_cards_dir=agent_cards_dir
        )
        self.add_mcp_server(agent_card_mcp_config)

    def add_mcp_server(self, config: MCPServerConfig):
        """Add an MCP server configuration"""
        self.mcp_manager.add_server(config)

    def add_a2a_server(self, server: A2AAgentServer):
        """Add an A2A agent server"""
        logger.info(f"Adding agent server: {server.name}")
        return self.a2a_manager.add_server(server)


    async def user_query(self, query: str, context_id: str, task_id: str):
        raise NotImplementedError()

    async def start_all(self):
        """Start all services in proper order"""
        logger.info("Starting service orchestration...")
        try:
            # Start MCP servers first (agents depend on them)
            logger.info("Starting MCP servers...")
            await self.mcp_manager.start_all()

            # Start A2A servers
            logger.info("Starting A2A agent servers...")
            await self.a2a_manager.start_all()

            logger.info("All services started successfully")

        except Exception as e:
            logger.error(f"Failed to start services: {e}")
            await self.shutdown_all()
            raise

    async def shutdown_all(self):
        """Shutdown all services in proper order"""
        logger.info("Shutting down all services...")

        try:
            # Shutdown A2A servers first (they depend on MCP)
            logger.info("Shutting down A2A servers...")
            await self.a2a_manager.stop_all()

            # Then shutdown MCP servers
            logger.info("Shutting down MCP servers...")
            await self.mcp_manager.stop_all()

            logger.info("All services stopped")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

    async def run(self):
        await self.start_all()

    async def run_until_shutdown(self):
        """Run all services and keep the orchestrator alive until shutdown signal."""
        await self.start_all()

        try:
            # Block the main coroutine until manually interrupted
            while True:
                await asyncio.sleep(1)
        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("Shutdown signal received (cancel or interrupt)")
        finally:
            await self.shutdown_all()

    def get_service_status(self) -> Dict[str, Any]:
        """Get status of all services"""
        return {
            "mcp_servers": self.mcp_manager.get_status(),
            "a2a_servers": {
                f"server-{i}": "running" if server.server else "stopped"
                for i, server in enumerate(self.a2a_manager.servers)
            },
        }

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.shutdown_all()
