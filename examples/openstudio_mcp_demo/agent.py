import asyncio
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.common.agent_registry import A2AAgentServer, A2AServerManager
from automa_ai.common.mcp_registry import MCPServerConfig, MCPServerManager
from examples.openstudio_mcp_demo.openstudio_mcp_server.server import serve

base_dir = Path(__file__).resolve().parent
env_path = base_dir / ".env"
load_dotenv(dotenv_path=env_path)

CHATBOT_SERVER_URL = os.getenv("CHATBOT_SERVER_URL", "http://localhost:9999")
CHAT_BOT_MODEL_NAME = os.getenv("CHAT_BOT_MODEL_NAME", "llama3.1:8b")
CHAT_BOT_MODEL_BASE_URL = os.getenv("CHAT_BOT_MODEL_BASE_URL") or None
OPENSTUDIO_MCP_HOST = os.getenv("OPENSTUDIO_MCP_HOST", "localhost")
OPENSTUDIO_MCP_PORT = int(os.getenv("OPENSTUDIO_MCP_PORT", "10210"))


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def build_openstudio_mcp_config() -> MCPServerConfig:
    return MCPServerConfig(
        name="openstudio_mcp",
        host=OPENSTUDIO_MCP_HOST,
        port=OPENSTUDIO_MCP_PORT,
        serve=serve,
        transport="sse",
    )


def build_agent_card() -> dict[str, Any]:
    sizing_skill = {
        "id": "hvac_sizing_assistant",
        "name": "OpenStudio HVAC Sizing Assistant",
        "description": "Runs a constrained OpenStudio sizing workflow via MCP tools.",
        "tags": ["openstudio", "mcp", "hvac_sizing"],
        "examples": [
            "Run a sizing workflow for model file:///tmp/demo.osm.",
            "Validate and size this model with default weather assumptions.",
        ],
    }

    return {
        "name": "OpenStudio MCP Sizing Agent",
        "description": "AgentFactory-based example agent wired to OpenStudio MCP tools.",
        "version": "0.1.0",
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "capabilities": {"streaming": True},
        "supportedInterfaces": [
            {
                "url": CHATBOT_SERVER_URL,
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "skills": [sizing_skill],
    }


def build_chatbot(mcp_config: MCPServerConfig, card: dict[str, Any]) -> AgentFactory:

    allowlist = _load_text(base_dir / "policy" / "tool_allowlist.yaml")
    run_gates = _load_text(base_dir / "policy" / "run_gates.yaml")
    skill_doc = _load_text(base_dir / "skills" / "hvac_sizing_assistant.md")

    instructions = f"""
You are an OpenStudio sizing workflow assistant.

Follow the skill instructions exactly:
{skill_doc}

Policy: tool allowlist
{allowlist}

Policy: run gates
{run_gates}

Execution rules:
- Only call tools with prefixes model.*, sim.*, results.*.
- Ask clarifying questions when required inputs are missing.
- Return structured JSON with assumptions, sizing result summary, and artifact IDs.
- Include a short trace of tools called (tool name and key IDs) in your final response.
""".strip()

    return AgentFactory(
        card=card,
        instructions=instructions,
        model_name=CHAT_BOT_MODEL_NAME,
        agent_type=GenericAgentType.LANGGRAPHCHAT,
        chat_model=GenericLLM.OLLAMA,
        model_base_url=CHAT_BOT_MODEL_BASE_URL,
        mcp_configs={"openstudio_mcp": mcp_config},
        enable_metrics=True,
        debug=True,
    )


async def main() -> None:
    mcp_config = build_openstudio_mcp_config()
    card = build_agent_card()
    chatbot = build_chatbot(mcp_config, card)

    mcp_manager = MCPServerManager()
    mcp_manager.add_server(mcp_config)

    chatbot_a2a = A2AAgentServer(chatbot, card)
    server_manager = A2AServerManager()
    server_manager.add_server(chatbot_a2a)

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
