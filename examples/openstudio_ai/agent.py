import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from automa_ai.common.agent_registry import A2AServerManager
from automa_ai.common.mcp_registry import MCPServerConfig, MCPServerManager
from automa_ai.config.agent_spec import YamlAgentSpec, load_a2a_server_from_yaml
from examples.openstudio_ai.openstudio_mcp_server.server import serve

base_dir = Path(__file__).resolve().parent
env_path = base_dir / ".env"
load_dotenv(dotenv_path=env_path)

CHATBOT_SERVER_URL = os.getenv("CHATBOT_SERVER_URL", "http://localhost:9999")
CHAT_BOT_MODEL_NAME = os.getenv("CHAT_BOT_MODEL_NAME", "llama3.1:8b")
CHAT_BOT_MODEL_BASE_URL = os.getenv("CHAT_BOT_MODEL_BASE_URL") or None
OPENSTUDIO_MCP_HOST = os.getenv("OPENSTUDIO_MCP_HOST", "localhost")
OPENSTUDIO_MCP_PORT = int(os.getenv("OPENSTUDIO_MCP_PORT", "10210"))
AGENT_SPEC_PATH = base_dir / "specs" / "openstudio_agent.yaml"


def build_openstudio_mcp_config() -> MCPServerConfig:
    return MCPServerConfig(
        name="openstudio_mcp",
        host=OPENSTUDIO_MCP_HOST,
        port=OPENSTUDIO_MCP_PORT,
        serve=serve,
        transport="sse",
    )


def load_openstudio_agent_spec(
    mcp_config: MCPServerConfig | None = None,
) -> YamlAgentSpec:
    """Load the YAML agent spec and apply environment-specific demo settings."""
    spec = YamlAgentSpec.from_yaml_file(AGENT_SPEC_PATH)
    spec.agent_card["supportedInterfaces"][0]["url"] = CHATBOT_SERVER_URL
    if not spec.model.name:
        spec.model.name = CHAT_BOT_MODEL_NAME
    if not spec.model.base_url:
        spec.model.base_url = CHAT_BOT_MODEL_BASE_URL

    if mcp_config is not None and spec.mcp is not None:
        server = spec.mcp.servers["openstudio_mcp"]
        server.host = mcp_config.host
        server.port = mcp_config.port
        server.transport = mcp_config.transport
        server.timeout = mcp_config.timeout
        server.sse_read_timeout = mcp_config.sse_read_timeout

    return spec


async def main() -> None:
    mcp_config = build_openstudio_mcp_config()
    agent_spec = load_openstudio_agent_spec(mcp_config)

    mcp_manager = MCPServerManager()
    mcp_manager.add_server(mcp_config)

    server_manager = A2AServerManager()
    server_manager.add_server(load_a2a_server_from_yaml(agent_spec))

    await mcp_manager.start_all()
    print(f"✅ MCP Server started at http://{mcp_config.host}:{mcp_config.port}/")

    await server_manager.start_all()
    print(f"✅ A2A Server started at {CHATBOT_SERVER_URL}")
    print("Type 'exit' or 'stop' to shut down.")

    loop = asyncio.get_event_loop()

    while True:
        cmd = await loop.run_in_executor(None, input, "> ")
        if cmd.strip().lower() in {"exit", "stop", "quit"}:
            break

    print("🛑 Stopping server...")
    await server_manager.stop_all()
    await mcp_manager.stop_all()
    print("🧹 Server stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
