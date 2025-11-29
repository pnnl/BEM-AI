################
# gbXML Agentic Network (ServiceOrchestrator pattern)
# - gbXML-only network (Planner → gbXML Agent (MCP tools) → Summary)
# - Uses the agent-cards A2A server for agent messaging
# - Starts a separate gbXML MCP server over SSE (http://127.0.0.1:10160)
################

import asyncio
import json
import logging
from pathlib import Path
from typing import Literal
import os
from pydantic import BaseModel, Field
from dotenv import load_dotenv
# --- Framework imports (automa_ai-style) ---
from a2a.types import AgentCard
from automa_ai.agents import GenericLLM, GenericAgentType
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.agents.orchestrator_network_agent import OrchestratorConfig
from automa_ai.common.agent_registry import A2AAgentServer
from automa_ai.common.mcp_registry import MCPServerConfig
from automa_ai.common.types import TaskList
from automa_ai.network.agentic_network import ServiceOrchestrator

# --- Import the gbXML MCP server you built ---
from app_mcps import model_mcp as gbxml_mcp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Base dir for this script (e.g., .../examples/gbxml)
BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / '.env'
load_dotenv(dotenv_path=env_path)
########################################################################################
# Prompts
########################################################################################
PLANNER_COT = """
You are a planning agent for gbXML-related queries.
Your job is to choose ONE gbXML MCP tool and gather the minimal inputs. 
Tools available (do not invent others):
- list_surfaces
- list_constructions
- get_surface_area
- get_surface_tilt
- get_surface_insulation

Always use chain-of-thought reasoning before generating tasks.
## QUESTION FORMAT
You question should contain both status and question and formatted as the example below:
{
    "status": "input_required",
    "question": {{add your question}}
}

CHAIN-OF-THOUGHT PROCESS:
Before each response, reason through:
1. What are my tools' capabilities? [Understand your tools' capability]
2. What information do I already have? [List all known information]
3. To leverage my tools' capabilities, what is the next unknown information? [Identify gap]
4. How should i naturally ask for this information? [Formulate question]
5. If I have all the information I need, I should now proceed to generating tasks
Always include a task to run simulation on original model. Do not generate tasks for data analysis, or data comparisons.

Typical inputs you must gather:
- gbxml_path (string; absolute or relative)
- surface_id (string; REQUIRED for get_surface_* tools) only for surface-specific tools

If information is missing, ask exactly ONE concise question.

QUESTION FORMAT (when info missing):
{
  "status": "input_required",
  "question": "Ask ONE clear question to obtain the missing field(s)"
}

OUTPUT FORMAT (valid JSON only):
{
  "original_query": "<original user query>",
  "blackboard": {
    "gbxml_path": "<string or null>",
    "surface_id": "<string or null>",
    "construction_id": "<string or null>",
    "tool_name": "list_surfaces|list_constructions|get_surface_area|get_surface_tilt|get_surface_insulation",
    "save_request_as": "<string or null>",
    "save_response_as": "<string or null>"
  },
  "status": "completed" | "input_required" | "error",
  "tasks": [
    {"id": 1, "description": "Call gbXML Agent tool", "status": "pending"},
    {"id": 2, "description": "Summarize results", "status": "pending"}
  ]
}
"""

GBXML_COT = """
You are the gbXML Agent. Your only job is to call ONE MCP tool from the gbXML server.

Use blackboard values if present:
- tool_name (required)
- gbxml_path (required for all tools)
- surface_id (required for get_surface_* tools)
- construction_id (optional)
- save_request_as / save_response_as (optional)

After the tool returns a text result, write it back to the blackboard as "gbxml_result_msg".

RESPONSE (valid JSON only):
{
  "status": "completed",
  "description": "Called gbXML MCP tool.",
  "blackboard": {
    "gbxml_result_msg": "<exact tool result string>"
  }
}
"""

SUMMARY_COT = """
Summarize the gbXML MCP result for the user.

Hints:
- Include tool_name and identifiers (surface_id if used).
- If present, restate numeric values (area m², tilt degrees, R-value m²·K/W).

OUTPUT (valid JSON only):
{
  "status": "completed",
  "description": "Final summary for the user",
  "blackboard": {
    "summary": "<one short paragraph summary>"
  }
}
"""

########################################################################################
# MCP config (SSE, separate from the A2A agent-cards server)
########################################################################################
gbxml_mcp_config = MCPServerConfig(
    name="gbxml_mcp",
    host="localhost",
    port=10160,
    serve=gbxml_mcp.serve,
    transport="sse",  # align with COMcheck pattern
)

########################################################################################
# Planner response schema
########################################################################################

class ResponseFormat(BaseModel):
    status: Literal["input_required", "completed", "error"] = "input_required"
    question: str = Field(
        description="If input is required, the question to the user",
        default=""
    )
    content: TaskList = Field(
        description="List of tasks when the plan is generated",
        default_factory=list
    )

########################################################################################
# Instantiate agents via AgentFactory
########################################################################################
planner_model_name = os.getenv("PLANNER_MODEL_NAME")
planner_model_base_url = os.getenv("PLANNER_MODEL_BASE_URL")
# Planner agent
planner_card_path = BASE_DIR / "agent_cards" / "planner_agent.json"
with Path.open(planner_card_path, encoding="utf-8") as f:
    planner_card = AgentCard(**json.load(f))

planner = AgentFactory(
    card=planner_card,
    instructions=PLANNER_COT,
    model_name=planner_model_name,
    agent_type=GenericAgentType.LANGGRAPH,
    chat_model=GenericLLM.OLLAMA,
    response_format=ResponseFormat,
    model_base_url=planner_model_base_url,
)

# gbXML specialist agent
gbxml_card_path = BASE_DIR / "agent_cards" / "gbxml_agent.json"
with Path.open(gbxml_card_path, encoding="utf-8") as f:
    gbxml_card = AgentCard(**json.load(f))

gbxml_agent = AgentFactory(
    card=gbxml_card,
    instructions=GBXML_COT,
    model_name="qwen3:4b",
    agent_type=GenericAgentType.LANGGRAPH,
    chat_model=GenericLLM.OLLAMA,
    mcp_configs={"gbxml_mcp": gbxml_mcp_config},  # exposes MCP tools
)

# Summary agent
summary_card_path = BASE_DIR / "agent_cards" / "summary_agent.json"
with Path.open(summary_card_path, encoding="utf-8") as f:
    summary_card = AgentCard(**json.load(f))

summary_agent = AgentFactory(
    card=summary_card,
    instructions=SUMMARY_COT,
    model_name="qwen3:4b",
    agent_type=GenericAgentType.LANGGRAPH,
    chat_model=GenericLLM.OLLAMA,
)

########################################################################################
# Main (ServiceOrchestrator-based network)
########################################################################################

async def main():
    # Orchestrator uses summary-style instructions, as in the combined example
    orchestrator_config = OrchestratorConfig(
        chat_model=GenericLLM.OLLAMA,
        model_name=planner_model_name,
        instruction=SUMMARY_COT,
        model_base_url=planner_model_base_url,
    )

    # You can adjust orchestrator_port if you want a specific A2A HTTP port
    gbxml_network = ServiceOrchestrator(
        orchestrator_config=orchestrator_config,
        orchestrator_port=10100,
        agent_cards_dir=BASE_DIR / "agent_cards",
    )

    # Register the gbXML MCP server so the gbXML specialist can use it
    gbxml_network.add_mcp_server(gbxml_mcp_config)

    # Wrap agents as A2A servers
    planner_server = A2AAgentServer(planner, planner_card)
    gbxml_server = A2AAgentServer(gbxml_agent, gbxml_card)
    summary_server = A2AAgentServer(summary_agent, summary_card)

    # Add A2A servers to the network
    gbxml_network.add_a2a_server(planner_server)
    gbxml_network.add_a2a_server(gbxml_server)
    gbxml_network.add_a2a_server(summary_server)

    await gbxml_network.run()
    print("✅ gbXML network started...")
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
    print("🛑 Stopping gbXML network...")
    await gbxml_network.shutdown_all()
    print("🧹 MCP and A2A Servers stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
