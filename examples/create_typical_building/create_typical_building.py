import asyncio
import os
from pathlib import Path
from a2a.types import AgentCard, AgentSkill, AgentCapabilities
from dotenv import load_dotenv

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.common.agent_registry import A2AServerManager, A2AAgentServer
from automa_ai.common.mcp_registry import MCPServerConfig, MCPServerManager

# Import MCP server
from mcp_server.src.server import serve

base_dir = Path(__file__).resolve().parent
env_path = base_dir / '.env'
load_dotenv(dotenv_path=env_path)

# Environment variables
CHATBOT_SERVER_URL = os.environ.get("CHATBOT_SERVER_URL", "http://localhost:8081")
chat_bot_model_name = os.environ.get("CHAT_BOT_MODEL_NAME", "gpt-4o")
chat_bot_base_url = os.environ.get("CHAT_BOT_MODEL_BASE_URL") or None
chat_bot_api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY") or None
CREATE_TYPICAL_BLDG_MCP_PORT = int(os.environ.get("CREATE_TYPICAL_BLDG_MCP_PORT", "8082"))
CREATE_TYPICAL_BLDG_MCP_HOST = os.environ.get("CREATE_TYPICAL_BLDG_MCP_HOST", "localhost")

########################################################################################
# MCP Server Configuration
########################################################################################
# Configure the OpenStudio Standards MCP server with SSE transport
create_typical_bldg_mcp_config = MCPServerConfig(
    name="create_typical_bldg_mcp",
    host=CREATE_TYPICAL_BLDG_MCP_HOST,
    port=CREATE_TYPICAL_BLDG_MCP_PORT,
    serve=serve,
    transport="sse"
)

########################################################################################
# Agent Skills
########################################################################################
geometry_generation_skill = AgentSkill(
    id="geometry_generation",
    name="Geometry Generation",
    description="Generate default building geometries based on ASHRAE building types and space types. Load OpenStudio models with predefined geometries for various building types like Office, Hospital, School, etc.",
    tags=["geometry", "building_model", "space_types"],
    examples=[
        "Generate a medium office building geometry",
        "Load the default geometry for a primary school",
        "Create a large hotel building model"
    ],
)

construction_envelope_skill = AgentSkill(
    id="construction_envelope",
    name="Construction and Envelope Configuration",
    description="Apply ASHRAE 90.1 construction sets and configure envelope parameters. Set default constructions based on climate zone, building type, and space type to ensure compliance with energy standards.",
    tags=["construction", "envelope", "ashrae_90.1", "energy_standards"],
    examples=[
        "Apply ASHRAE 90.1-2013 constructions for climate zone 4A",
        "Set envelope parameters for a retail building in zone 5B",
        "Configure construction set for an office building"
    ],
)

########################################################################################
# Agent Instructions (Chain-of-Thought Prompt)
########################################################################################
FOUNDATIONAL_GEOMETRY_COT = """
You are a foundational geometry and building envelope specialist. Your role is to create the scaffolding for 
energy models by generating building geometries and applying appropriate construction sets based on ASHRAE standards.

## YOUR CAPABILITIES
1. **Geometry Generation**: Generate default building geometries based on ASHRAE building types (Office, Hospital, 
   School, Hotel, Retail, etc.)
2. **Construction Set Application**: Apply ASHRAE 90.1 construction sets based on:
   - Climate zone (e.g., ASHRAE 169-2013-4A)
   - Building type (e.g., Office, Retail, School)
   - ASHRAE standard version (90.1-2004, 90.1-2007, 90.1-2010, 90.1-2013, 90.1-2016, 90.1-2019)

## SYSTEM INFORMATION
This system is running on Linux. ALWAYS use forward slashes (/) in file paths, never backslashes (\\).

## WORKFLOW
When a user asks to create a building model, follow this process:

1. **Gather Requirements**: Determine what information you need:
   - Building type (required for geometry)
   - Climate zone (required for construction set)
   - ASHRAE standard version (default to 90.1-2013 if not specified)
   - Save directory path (where to save the resulting OSM file)

2. **Ask for Missing Information**: If any required information is missing, ask the user clearly and concisely.

3. **Generate Geometry**: Use the appropriate tools to load or generate the default geometry for the specified building type.

4. **Apply Construction Set**: Apply the ASHRAE 90.1 construction set based on the climate zone, building type, 
   and standard version.

5. **Save Results**: Save the completed model to the specified directory.

## IMPORTANT GUIDELINES
- Always confirm the save directory path before saving files
- Provide clear feedback about what was created
- If errors occur, explain them in user-friendly terms
- The resulting OpenStudio Model (.osm file) will serve as the foundation for adding HVAC, lighting, 
  service hot water, and other building systems in future steps

## AVAILABLE BUILDING TYPES
Available geometries include: Office (Small, Medium, Large), Hospital, School (Primary, Secondary), 
Hotel (Small, Large), Retail, Warehouse, Restaurant, and others.

## CLIMATE ZONES
Common climate zones include: 1A, 2A, 2B, 3A, 3B, 3C, 4A, 4B, 4C, 5A, 5B, 5C, 6A, 6B, 7A, 7B, 8A
(format: ASHRAE 169-2013-<zone>)

Be helpful, precise, and ensure the foundational geometry you create is ready for subsequent model development.
"""

########################################################################################
# Agent Card
########################################################################################
foundational_geometry_card = AgentCard(
    name="Foundational Geometry Agent",
    description="Creates foundational building geometry models with ASHRAE-compliant construction sets. "
                "Generates default building geometries based on use type and applies appropriate envelope "
                "parameters based on climate zone and energy standards. This agent provides the scaffolding "
                "for subsequent HVAC, lighting, and other building system modeling.",
    url=CHATBOT_SERVER_URL,
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[geometry_generation_skill, construction_envelope_skill],
    supports_authenticated_extended_card=False,
)

########################################################################################
# Agent Factory
########################################################################################
# Initialize foundational geometry agent with MCP server configuration
foundational_geometry_agent = AgentFactory(
    card=foundational_geometry_card,
    instructions=FOUNDATIONAL_GEOMETRY_COT,
    model_name=chat_bot_model_name,
    agent_type=GenericAgentType.LANGGRAPHCHAT,
    chat_model=GenericLLM.CLAUDE,  # Changed from OLLAMA to CLAUDE
    model_base_url=chat_bot_base_url,
    api_key=chat_bot_api_key,  # The agent can use this API key when relevant.
    mcp_configs={"create_typical_bldg_mcp": create_typical_bldg_mcp_config},  # Enable MCP server with SSE transport
    enable_metrics=True,
    debug=True
)

# Wrap agent in A2A agent server
foundational_geometry_a2a = A2AAgentServer(foundational_geometry_agent, foundational_geometry_card)

# Initialize MCP server manager
mcp_manager = MCPServerManager()
mcp_manager.add_server(create_typical_bldg_mcp_config)

# Initialize A2A server manager
server_manager = A2AServerManager()
server_manager.add_server(foundational_geometry_a2a)

########################################################################################
# Main Entry Point
########################################################################################
async def main():
    """Start A2A agent server with MCP tools"""
    
    # Start MCP server first
    await mcp_manager.start_all()
    print(f"✅ MCP Server started at http://{CREATE_TYPICAL_BLDG_MCP_HOST}:{CREATE_TYPICAL_BLDG_MCP_PORT}")
    
    # Start A2A agent server
    await server_manager.start_all()
    print(f"✅ A2A Server started at {CHATBOT_SERVER_URL}")
    print(f"🏗️  Foundational Geometry Agent ready with OpenStudio tools")
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
    print("🛑 Stopping servers...")
    await server_manager.stop_all()
    await mcp_manager.stop_all()
    print("🧹 Servers stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
