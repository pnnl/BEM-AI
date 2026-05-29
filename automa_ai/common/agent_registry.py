import asyncio
import inspect
import logging
import sys
from copy import deepcopy
from multiprocessing import Process
from typing import Any, Optional, List, Dict, Callable
from urllib.parse import urlparse, urlunparse

import uvicorn
from google.protobuf.json_format import MessageToDict, ParseDict
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard
from a2a.utils.constants import DEFAULT_RPC_URL
from a2a.server.agent_execution import AgentExecutor

from automa_ai.common.agent_executor import GenericAgentExecutor
from automa_ai.common.base_agent import BaseAgent
from automa_ai.common.utils import wait_for_port
from automa_ai.common.setup_logging import _init_child_logging


logger = logging.getLogger(__name__)


def _child_entrypoint(run_fn, logging_config):
    _init_child_logging(logging_config)

    # Load plugins BEFORE any agent is created
    from automa_ai.common.utils import (
        load_memory_store_plugins,
        load_token_usage_store_plugins,
        load_tool_plugins,
    )

    load_memory_store_plugins()
    load_token_usage_store_plugins()
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


def _normalize_card_data(card: AgentCard | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(card, AgentCard):
        return MessageToDict(card, preserving_proto_field_name=False)
    return deepcopy(card)


def _get_primary_interface(card_data: Dict[str, Any]) -> Dict[str, Any]:
    interfaces = card_data.get("supportedInterfaces") or card_data.get(
        "supported_interfaces"
    )
    if not interfaces:
        raise ValueError(
            f"Agent card '{card_data.get('name', '<unknown>')}' does not define any supported interfaces."
        )
    return interfaces[0]


def _get_primary_interface_url(card_data: Dict[str, Any]) -> str:
    return _get_primary_interface(card_data)["url"]


def _replace_agent_url_path(url: str, base_url_path: str | None) -> str:
    parsed = _parse_agent_url(url)
    path = base_url_path or "/"
    if path != "/" and not path.endswith("/"):
        path = f"{path}/"
    return urlunparse(
        parsed._replace(
            path=path,
            params="",
            query="",
            fragment="",
        )
    )


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


def _build_generic_agent_executor(agent: BaseAgent) -> AgentExecutor:
    return GenericAgentExecutor(agent=agent)


class A2AAgentServer:
    def __init__(
        self,
        agent_builder: Callable[[], BaseAgent],
        card: AgentCard | Dict[str, Any],
        log_dir: str = "./logs",
        base_url_path: str | None = None,
        health_check_path: str = "/health",
        executor_builder: Callable[[BaseAgent], AgentExecutor] | None = None,
    ):
        self.agent_builder = agent_builder
        self.executor_builder = executor_builder or _build_generic_agent_executor
        self._card_data = _normalize_card_data(card)
        self.name = self._card_data["name"]
        parsed_url = _parse_agent_url(_get_primary_interface_url(self._card_data))
        self.host_name, self.port = parsed_url.hostname, parsed_url.port
        self.base_url_path = _normalize_base_path(
            base_url_path if base_url_path is not None else parsed_url.path
        )
        if self.base_url_path:
            primary_interface = _get_primary_interface(self._card_data)
            primary_interface["url"] = _replace_agent_url_path(
                primary_interface["url"],
                self.base_url_path,
            )
        self.log_dir = log_dir
        self.server: Optional[uvicorn.Server] = None
        self.shutdown_event = asyncio.Event()
        self.health_check_path = health_check_path
        self._agent: Optional[BaseAgent] = None

    @property
    def card(self) -> AgentCard:
        return ParseDict(self._card_data, AgentCard())

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
            card = self.card
            # Create client and request handler
            request_handler = DefaultRequestHandler(
                agent_executor=self.executor_builder(self._agent),
                task_store=InMemoryTaskStore(),
                agent_card=card,
            )

            # Always add health check endpoint and handle base path if specified
            from starlette.applications import Starlette
            from starlette.routing import Mount, Route
            from starlette.responses import JSONResponse

            async def health_check(request):
                return JSONResponse(self._build_health_response())

            a2a_routes = [
                *create_agent_card_routes(card),
                *create_jsonrpc_routes(
                    request_handler=request_handler,
                    rpc_url=DEFAULT_RPC_URL,
                ),
            ]
            a2a_app = Starlette(routes=a2a_routes)

            routes = [
                Route(self.health_check_path, health_check),
                Mount(self.base_url_path or "/", app=a2a_app),
            ]
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
