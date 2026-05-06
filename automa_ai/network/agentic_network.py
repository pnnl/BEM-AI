import asyncio
import logging
from pathlib import Path
from typing import Dict, Any

from automa_ai.agents import GenericAgentType
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.agents.orchestrator_network_agent import OrchestratorConfig
from automa_ai.common.agent_registry import A2AServerManager, A2AAgentServer
from automa_ai.common.file_util import verify_directory_and_json_files
from automa_ai.common.mcp_registry import MCPServerManager, MCPServerConfig
from automa_ai.common.utils import get_agent_mcp_server_config, deprecated
from automa_ai.mcp_servers.agent_card_server import serve

logger = logging.getLogger(__name__)

@deprecated("Use MultiAgentNetwork instead. This class will be removed in v0.3.x")
class ServiceOrchestrator:
    def __init__(self, orchestrator_config: OrchestratorConfig, agent_cards_dir: str, orchestrator_port: int = 10000, agent_card_port: int = 10100):
        """
        :param orchestrator: orchestrator agent
        :param agent_cards_dir: directory to agent cards.
        """
        self.mcp_manager = MCPServerManager(logging_config=orchestrator_config.logging_config)
        self.a2a_manager = A2AServerManager(logging_config=orchestrator_config.logging_config)
        self.port_list = []
        # Check agent_card_validity
        self.orchestrator_port = orchestrator_port
        self.agent_card_port = agent_card_port
        self.orchestrator_config = orchestrator_config

        assert verify_directory_and_json_files(agent_cards_dir), "Invalid or empty directory"

        self._init_agent_card_mcp(agent_cards_dir)
        self._init_orchestrator_agent(orchestrator_config)

    def _init_orchestrator_agent(self, orchestrator_config: OrchestratorConfig):
        # Develop Agent Card

        skill = {
            "id": "executor",
            "name": "Task Executor",
            "description": "Orchestrates the task generation and execution, takes help from the planner to generate tasks",
            "tags": ["execute plan"],
            "examples": ["Plan my trip to London, submit an expense report."],
        }

        # --8<-- [start:AgentCard]
        # This will be the public-facing agent card
        orchestrator_agent_card = {
            "name": "Orchestrator Agent",
            "description": "Orchestrates the task generation and execution.",
            "version": "1.0.0",
            "defaultInputModes": ["text"],
            "defaultOutputModes": ["text"],
            "capabilities": {
                "streaming": True,
                "pushNotifications": True,
            },
            "supportedInterfaces": [
                {
                    "url": f"http://localhost:{self.orchestrator_port}/",
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "1.0",
                }
            ],
            "skills": [skill],
        }

        orchestrator = AgentFactory(
            card=orchestrator_agent_card,
            instructions=orchestrator_config.instruction,
            model_name=orchestrator_config.model_name,
            agent_type=GenericAgentType.ORCHESTRATOR,
            chat_model=orchestrator_config.chat_model,
            model_base_url=orchestrator_config.model_base_url,
        )

        orchestrator_a2a_server = A2AAgentServer(orchestrator, orchestrator_agent_card)
        self.a2a_manager.add_server(orchestrator_a2a_server)

    def _init_agent_card_mcp(self, agent_cards_dir: str):
        agent_card_mcp_config = MCPServerConfig(
            name="a2a-agent-cards",
            host="localhost",
            port=self.agent_card_port,
            serve=serve,
            transport="sse",
            agent_cards_dir=agent_cards_dir
        )
        self.add_mcp_server(agent_card_mcp_config)
        return True

    def add_mcp_server(self, config: MCPServerConfig):
        """Add an MCP server configuration"""
        assert config.port not in self.port_list, f"Port {config.port} is occupied in the network, please change to another port for {config.name}."
        self.port_list.append(config.port)
        self.mcp_manager.add_server(config)
        return True

    def add_a2a_server(self, server: A2AAgentServer):
        """Add an A2A agent server"""
        assert server.port not in self.port_list, f"Port {server.port} is occupied in the network, please change to another port for {server.name}."
        self.port_list.append(server.port)
        self.a2a_manager.add_server(server)
        return True

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


class MultiAgentNetwork:
    def __init__(self, agent_cards_dir: Path | str):
        self.mcp_manager = MCPServerManager()
        self.a2a_manager = A2AServerManager()
        self.port_list = []
        self.network_entry_port = None
        self.network_entry_host = None

        assert verify_directory_and_json_files(agent_cards_dir), "Invalid or empty directory"

        self._init_agent_card_mcp(agent_cards_dir)

    def _init_agent_card_mcp(self, agent_cards_dir: str):
        agent_card_server_config = get_agent_mcp_server_config()
        agent_card_mcp_config = MCPServerConfig(
            name="a2a-agent-cards",
            host=agent_card_server_config.host,
            port=agent_card_server_config.port,
            serve=serve,
            transport=agent_card_server_config.transport,
            agent_cards_dir=agent_cards_dir
        )
        self.add_mcp_server(agent_card_mcp_config)
        return True

    def add_entry_agent(self, server: A2AAgentServer):
        self.add_a2a_server(server)
        # ensure success add and then process the port and host_name
        self.network_entry_port = server.port
        self.network_entry_host = server.host_name

    def get_entry_url(self) -> str:
        return f"http://{self.network_entry_host}:{self.network_entry_port}"

    def get_entry_port(self) -> int:
        return self.network_entry_port

    def get_entry_host(self) -> str:
        return self.network_entry_host

    def add_mcp_server(self, config: MCPServerConfig):
        """Add an MCP server configuration"""
        assert config.port not in self.port_list, f"Port {config.port} is occupied in the network, please change to another port for {config.name}."
        self.port_list.append(config.port)
        self.mcp_manager.add_server(config)
        return True

    def add_a2a_server(self, server: A2AAgentServer):
        """Add an A2A agent server"""
        assert server.port not in self.port_list, f"Port {server.port} is occupied in the network, please change to another port for {server.name}."
        self.port_list.append(server.port)
        self.a2a_manager.add_server(server)
        return True

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
