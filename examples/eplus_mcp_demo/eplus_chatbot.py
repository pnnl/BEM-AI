import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from automa_ai.common.mcp_registry import MCPServerConfig, MCPServerManager

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.common.agent_registry import A2AServerManager, A2AAgentServer

from energyplus_mcp_server.server import serve

base_dir = Path(__file__).resolve().parent
env_path = base_dir / ".env"
load_dotenv(dotenv_path=env_path)

CHATBOT_SERVER_URL = os.environ.get("CHATBOT_SERVER_URL")
chat_bot_model_name = os.environ.get("CHAT_BOT_MODEL_NAME")
chat_bot_base_url = os.environ.get("CHAT_BOT_MODEL_BASE_URL") or None
eplus_mcp_port = int(os.environ.get("EPLUS_MCP_PORT"))
eplus_mcp_host = os.environ.get("EPLUS_MCP_HOST")

eplus_mcp_config = MCPServerConfig(
    name="eplus_mcp",
    host=eplus_mcp_host,
    port=eplus_mcp_port,
    serve=serve,
    transport="sse",
)

config_skill = {
    "id": "model_configuration",
    "name": "Model Config and Loading",
    "description": "Load EnergyPlus IDF models, validate model, get model summary",
    "tags": ["model_config"],
    "examples": [
        "Can you help me validate the EnergyPlus model?",
        "What is the simulation settings?",
    ],
}

inspect_skill = {
    "id": "model_inspect",
    "name": "Model Inspection",
    "description": "Inspect energy model components such as zones, surfaces, materials etc. ",
    "tags": ["model_inspect"],
    "examples": [
        "Get materials from this IDF file",
        "Perform analysis on the schedules",
    ],
}

modify_skill = {
    "id": "model_modify",
    "name": "Model Modification",
    "description": "Modify data in the objects such as modify people objects, lights objects, and simulation controls",
    "tags": ["model_inspect"],
    "examples": [
        "Get materials from this IDF file",
        "Perform analysis on the schedules",
    ],
}

simulation_skill = {
    "id": "sim_skill",
    "name": "Simulation and Results",
    "description": "Run simulation, retrieve energy outputs from simulations",
    "tags": ["model_simulation"],
    "examples": ["Run energyplus simulation", "Create interactive plots"],
}

CHAT_COT = f"""
You are an EnergyPlus expert and can leverage tools provided to answer user questions about EnergyPlus IDF files.
Your goal is to assist users by providing detailed and accurate information.

## QUESTION FORMAT
User questions should contain both status and question, formatted as follows:
{{ "status": "input_required", "question": {{add your question}} }}

## PROVIDING CONTEXT
When asking a question, please provide relevant context about the EnergyPlus model or IDF file you are working with. This may include:
- The name of the IDF file
- A brief description of the building or system being modeled
- Any specific components or features you are trying to analyze or modify
- Or ask for the IDF file directory if it is unknown

## CHAIN-OF-THOUGHT PROCESS
Before each response, reason through:
1. What information do I already have? [List all known information]
2. What is the next unknown information needed to make a tool call? [Identify gap]
3. How should I naturally ask for this information? [Formulate question]
4. If I have all the necessary information, proceed to make tool calls

## COMMON TERMINOLOGY
IDF or idf stands for input data file, a file type that hosts EnergyPlus models. In user questions, EnergyPlus model and IDF are often used interchangeably.

Please provide detailed and specific questions about your EnergyPlus model or IDF file, including any relevant context, to help me better assist you.
"""

# --8<-- [start:AgentCard]
# This will be the public-facing agent card
public_agent_card = {
    "name": "EnergyPlus Assistance Agent",
    "description": (
        "An EnergyPlus agent provides helps on configuring and summary IDF files, "
        "inspect objects in the files, modify objects and analyze simulation outputs."
    ),
    "version": "1.0.0",
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
    "skills": [config_skill, inspect_skill, modify_skill, simulation_skill],
}

# Initialize chatbot agent
chatbot = AgentFactory(
    card=public_agent_card,
    instructions=CHAT_COT,
    model_name=chat_bot_model_name,
    agent_type=GenericAgentType.LANGGRAPHCHAT,
    chat_model=GenericLLM.OLLAMA,
    model_base_url=chat_bot_base_url,
    mcp_configs={"eplus_mcp": eplus_mcp_config},
    debug=True,
)

# Wrap chatbot agent in A2A agent server
chatbot_a2a = A2AAgentServer(chatbot, public_agent_card)

# Initialize A2A server manager
server_manager = A2AServerManager()
# Add server
server_manager.add_server(chatbot_a2a)

# Initialize MCP server manager
mcp_manager = MCPServerManager()
mcp_manager.add_server(eplus_mcp_config)


# Start network
async def main():
    await mcp_manager.start_all()
    print(
        f"✅ MCP Server started at http://{eplus_mcp_config.host}:{eplus_mcp_config.port}/"
    )

    await server_manager.start_all()
    print(f"✅ A2A Server started at {CHATBOT_SERVER_URL}")
    print("Type 'exit' or 'stop' to shut down.")

    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    async def wait_for_input():
        while True:
            cmd = await loop.run_in_executor(None, input, "> ")
            if cmd.strip().lower() in {"exit", "stop", "quit"}:
                stop_event.set()
                break

    await wait_for_input()
    print("🛑 Stopping server...")
    await server_manager.stop_all()
    print("🧹 Server stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
