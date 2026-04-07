import asyncio
import inspect
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

from automa_ai.common.agent_executor import GenericAgentExecutor
from automa_ai.common.base_agent import BaseAgent
from automa_ai.common.utils import wait_for_port
from automa_ai.common.setup_logging import _init_child_logging


logger = logging.getLogger(__name__)


def _child_entrypoint(run_fn, logging_config):
    _init_child_logging(logging_config)

    # Load plugins BEFORE any agent is created
    from automa_ai.common.utils import load_memory_store_plugins, load_tool_plugins

    load_memory_store_plugins()
    load_tool_plugins()
    run_fn()


def _normalize_base_path(path: str | None) -> str | None:
    if not path:
        return None
    normalized = path.strip()
    if not normalized:
        return None
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if normalized != "/" and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return None if normalized == "/" else normalized


def _parse_agent_url(url: str):
    parsed = urlparse(url)
    if not parsed.hostname or not parsed.port:
        parsed = urlparse(f"http://{url}")
    if not parsed.hostname or not parsed.port:
        raise ValueError(
            f"Invalid agent url '{url}'. Expected host and port, e.g. 'http://0.0.0.0:20000'."
        )
    return parsed


def _close_agent(agent: BaseAgent) -> None:
    close_fn = getattr(agent, "close", None)
    if not callable(close_fn):
        return

    try:
        result = close_fn()
        if inspect.isawaitable(result):
            asyncio.run(result)
    except Exception:
        logger.exception("Failed to close agent %s cleanly.", agent.agent_name)


class A2AAgentServer:
    def __init__(
        self,
        agent_builder: Callable[[], BaseAgent],
        card: AgentCard,
        log_dir: str = "./logs",
        base_url_path: str | None = None,
        health_check_path: str = "/health",
        enable_health_check: bool = True,
    ):
        self.agent_builder = agent_builder
        self.card = card
        self.name = card.name
        parsed_url = _parse_agent_url(self.card.url)
        self.host_name, self.port = parsed_url.hostname, parsed_url.port
        self.base_url_path = _normalize_base_path(
            base_url_path if base_url_path is not None else parsed_url.path
        )
        self.log_dir = log_dir
        self.server: Optional[uvicorn.Server] = None
        self.shutdown_event = asyncio.Event()
        self.health_check_path = health_check_path
        self.enable_health_check = enable_health_check
        self._agent: Optional[BaseAgent] = None

    def _build_health_response(self) -> dict:
        """Override this to customize the health check response."""
        return {
            "status": "healthy" if self._agent is not None else "unhealthy",
            "agent": self.name,
        }

    def run(self):
        self._agent = None
        try:
            logger.info("Building the agent....")
            self._agent = self.agent_builder()
            logger.info(f"complete agent bootup for agent {self._agent.agent_name}....")
            # Create client and request handler
            request_handler = DefaultRequestHandler(
                agent_executor=GenericAgentExecutor(agent=self._agent),
                task_store=InMemoryTaskStore(),
            )

            # Create server
            server = A2AStarletteApplication(
                agent_card=self.card,
                http_handler=request_handler,
            )

            app = server.build()
            
            if self.enable_health_check or self.base_url_path:
                from starlette.applications import Starlette
                from starlette.routing import Mount, Route

                routes = []

                if self.enable_health_check:
                    from starlette.responses import JSONResponse

                    async def health_check(request):
                        return JSONResponse(self._build_health_response())

                    routes.append(Route(self.health_check_path, health_check))

                routes.append(Mount(self.base_url_path or "/", app=app))
                app = Starlette(routes=routes)

                if self.base_url_path:
                    logger.info("Mounting A2A server at base path %s", self.base_url_path)

            logger.info(f"Starting server on {self.host_name}:{self.port}")

            # Run the server
            uvicorn.run(app, host=self.host_name, port=self.port, log_level="info")
            logger.info("Uvicorn server exited")
        except Exception as e:
            logger.error(f"An error occurred during server startup: {e}")
            sys.exit(1)
        finally:
            if self._agent is not None:
                _close_agent(self._agent)


class A2AServerManager:
    def __init__(self, logging_config: dict | None = None):
        self.servers: List[A2AAgentServer] = []
        self.processes: Dict[str, Process] = {}
        self.logging_config = logging_config

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
            process = Process(
                target=_child_entrypoint,
                args=(server.run, self.logging_config),
            )
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
