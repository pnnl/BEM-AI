import asyncio
import logging
import sys
from multiprocessing import Process
from typing import Optional, List, Dict, Callable
from urllib.parse import urlparse

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard

from common.agent_executor import GenericAgentExecutor
from common.base_agent import BaseAgent
from common.utils import wait_for_port

logger = logging.getLogger(__name__)


class A2AAgentServer:
    def __init__(self, agent_builder: Callable[[], BaseAgent], card: AgentCard):
        self.agent_builder = agent_builder
        self.card = card
        self.name = card.name
        parsed_url = urlparse(self.card.url)
        self.host_name = parsed_url.hostname
        self.port = parsed_url.port

        self.server: Optional[uvicorn.Server] = None
        self.shutdown_event = asyncio.Event()

    def run(self):
        try:
            logger.info("Building the agent....")
            agent = self.agent_builder()
            logger.info(f"complete agent bootup for agent {agent.agent_name}....")
            # Create client and request handler
            request_handler = DefaultRequestHandler(
                agent_executor=GenericAgentExecutor(agent=agent),
                task_store=InMemoryTaskStore(),
            )

            # Create server
            server = A2AStarletteApplication(
                agent_card=self.card, http_handler=request_handler
            )

            logger.info(f"Starting server on {self.host_name}:{self.port}")

            # Run the server
            uvicorn.run(
                server.build(), host=self.host_name, port=self.port, log_level="info"
            )
            logger.info("Uvicorn server exited")
        except Exception as e:
            logger.error(f"An error occurred during server startup: {e}")
            sys.exit(1)


class A2AServerManager:
    def __init__(self):
        self.servers: List[A2AAgentServer] = []
        self.processes: Dict[str, Process] = {}

    def add_server(self, agent_server: A2AAgentServer) -> bool:
        """Add an agent configuration"""
        self.servers.append(agent_server)
        return True

    async def start_all(self) -> List[Process]:
        """Boot up all agents - simple version"""
        processes = []

        for server in self.servers:
            server_name = server.name
            logger.info(f"Booting agent: {server_name}")
            # Create and start process
            process = Process(target=server.run)
            process.start()

            try:
                # Wait for port to be ready
                wait_for_port(server.host_name, server.port)
                logger.info(
                    f"Agent {server_name} is booted and accepting connections on {server.host_name}:{server.port}"
                )
                processes.append(process)
                self.processes[server_name] = process
                logger.info(f"Successfully booted agent: {server_name}")
            except TimeoutError as e:
                logger.error(f"Agent {server_name} failed to start: {e}")
                raise

        return processes

    async def stop_all(self) -> bool:
        """Shutdown all agents - simple version"""
        logger.info("Shutting down all agents...")

        for name, process in self.processes.items():
            try:
                logger.info(f"Terminating agent: {name}")
                process.terminate()  # Send SIGTERM (soft stop)
                process.join(timeout=5)

                if process.is_alive():
                    logger.warning(
                        f"Agent {name} didn't terminate gracefully, forcing kill"
                    )
                    process.kill()
                    process.join(timeout=2)

                logger.info(f"Agent {name} stopped successfully")

            except Exception as e:
                logger.error(f"Failed to stop agent {name}: {e}")

        self.processes.clear()
        logger.info("All agents shut down")
        return True

    def get_status(self) -> Dict[str, str]:
        """Get status of all agents"""
        status = {}
        for agent in self.servers:
            name = agent.card.name
            if name in self.processes and self.processes[name].is_alive():
                status[name] = f"Running on {agent.host_name}:{agent.port}"
            else:
                status[name] = "Stopped"
        return status

    def list_agents(self) -> List[str]:
        """List all configured agents"""
        return [agent.card.name for agent in self.servers]
