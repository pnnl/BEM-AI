# Configure logging
import logging
from dataclasses import dataclass
from multiprocessing import Process
from typing import Dict, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server"""

    name: str
    host: str
    port: int
    serve: callable
    transport: str = "sse"
    agent_cards_dir: str = "/src"


class MCPServerManager:
    """Simple MCP Server Manager"""

    def __init__(self):
        self.servers: Dict[str, Process] = {}
        self.configs: Dict[str, MCPServerConfig] = {}

    def add_server(self, config: MCPServerConfig) -> bool:
        """Add a server configuration"""
        if config.name in self.configs:
            logger.warning(f"Server {config.name} already exists")
            return False

        self.configs[config.name] = config
        logger.info(f"Added server configuration: {config.name}")
        return True

    async def start_server(self, name: str) -> bool:
        """Start a specific server"""
        if name not in self.configs:
            logger.error(f"Server {name} not found in configurations")
            return False

        if name in self.servers and self.servers[name].is_alive():
            logger.warning(f"Server {name} is already running")
            return False

        config = self.configs[name]

        # Create and start the process
        if name == "a2a-agent-cards":
            # Default agent card mcp
            print("Process booting up the agent cards server")
            process = Process(
                target=config.serve,
                args=(config.host, config.port, config.transport, config.agent_cards_dir),
                daemon=True,
                name=f"mcp-{name}",
            )
        else:
            process = Process(
                target=config.serve,
                args=(config.host, config.port, config.transport),
                daemon=True,
                name=f"mcp-{name}",
            )

        try:
            process.start()
            self.servers[name] = process

            # Wait for the server to be ready
            from common.utils import wait_for_port
            wait_for_port(config.host, config.port)
            logger.info(
                f"Server {name} started successfully on {config.host}:{config.port}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to start server {name}: {e}")
            if name in self.servers:
                del self.servers[name]
            return False

    async def stop_server(self, name: str) -> bool:
        """Stop a specific server"""
        if name not in self.servers:
            logger.warning(f"Server {name} is not running")
            return False

        try:
            process = self.servers[name]
            process.terminate()  # Send SIGTERM (soft stop)
            process.join(timeout=5)

            if process.is_alive():
                logger.warning(
                    f"Server {name} didn't terminate gracefully, forcing kill"
                )
                process.kill()
                process.join(timeout=2)

            del self.servers[name]
            logger.info(f"Server {name} stopped successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to stop server {name}: {e}")
            return False

    async def start_all(self) -> Dict[str, bool]:
        """Start all configured servers"""
        results = {}
        for name in self.configs:
            results[name] = await self.start_server(name)
        return results

    async def stop_all(self) -> Dict[str, bool]:
        """Stop all running servers"""
        results = {}
        for name in list(self.servers.keys()):
            results[name] = await self.stop_server(name)
        return results

    def get_status(self) -> Dict[str, str]:
        """Get status of all servers"""
        status = {}
        for name, config in self.configs.items():
            if name in self.servers and self.servers[name].is_alive():
                status[name] = f"Running on {config.host}:{config.port}"
            else:
                status[name] = "Stopped"
        return status

    def list_servers(self) -> List[str]:
        """List all configured servers"""
        return list(self.configs.keys())

    def cleanup(self):
        """Clean up all servers"""
        self.stop_all()
        logger.info("MCP Manager cleanup completed")
