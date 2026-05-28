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
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from typing import Literal

from automa_ai.agents import GenericLLM, GenericAgentType
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.common.agent_registry import A2AAgentServer
from automa_ai.common.mcp_registry import MCPServerConfig
from app_mcps import model_mcp
from automa_ai.common.types import TaskList
from automa_ai.network.agentic_network import MultiAgentNetwork

# --- Import the gbXML MCP server you built ---
from app_mcps import model_mcp as gbxml_mcp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Base dir for this script (e.g., .../examples/gbxml)
BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path)
########################################################################################
# Prompts
########################################################################################
PLANNER_COT = """
You are a planning agent for gbXML-related queries.
Your job is to choose ONE gbXML MCP tool and gather the minimal inputs. 
You need to based on user query to get input information like gbxml_path, surface_id, construction_id etc.
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
    [optional] "construction_id": "<string or null>",
    "tool_name": "list_surfaces|list_constructions|get_surface_area|get_surface_tilt|get_surface_insulation",
    [optional] "save_request_as": "<string or null>",
    [optional] "save_response_as": "<string or null>"
  },
  "status": "completed" | "input_required" | "error",
  "tasks": [
    {"id": 1, "description": "sample task 1", "status": "pending"},
    {"id": 2, "description": "sample task 2", "status": "pending"}
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
Your job is to summarize the work that has performed.
Your summary shall follow the format below.
### Task
{query}

### Blackboard Updates
In this section, provide a summary based on {blackboard}, especially focusing on the "gbxml_result_msg" content.

### Summary
Based on the above information, summarize the work that has performed in this task.
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
        description="If input is required, the question to the user", default=""
    )
    content: TaskList = Field(
        description="List of tasks when the plan is generated", default_factory=list
    )


########################################################################################
# Instantiate agents via AgentFactory
########################################################################################
planner_model_name = (
    "llama3.3:70b"  # os.getenv("PLANNER_MODEL_NAME") #need to set env var or hardcode
)
planner_model_base_url = "http://rc-chat.pnl.gov:11434"  # os.getenv("PLANNER_MODEL_BASE_URL") #need to set env var or hardcode
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

# Orchestrator agent
orchestrator_agent_card_path = BASE_DIR / "agent_cards" / "orchestrator_agent.json"
with Path.open(orchestrator_agent_card_path) as file:
    data = json.load(file)
    orchestrator_agent_card = AgentCard(**data)

orchestrator_agent = AgentFactory(
    card=orchestrator_agent_card,
    instructions=SUMMARY_COT,
    model_name=planner_model_name,
    model_base_url=planner_model_base_url,
    agent_type=GenericAgentType.ORCHESTRATOR,
    chat_model=GenericLLM.OLLAMA,
    debug=True,
)

########################################################################################
# Main
########################################################################################


async def main():
    automa_network = MultiAgentNetwork(agent_cards_dir=BASE_DIR / "agent_cards")
    # Register both MCP servers so specialists can use them
    automa_network.add_mcp_server(gbxml_mcp_config)

    # Wrap agents as A2A servers
    orchestrator_server = A2AAgentServer(orchestrator_agent, orchestrator_agent_card)
    planner_server = A2AAgentServer(planner, planner_card)
    gbxml_server = A2AAgentServer(gbxml_agent, gbxml_card)

    # Add A2A servers to the network
    automa_network.add_entry_agent(orchestrator_server)
    automa_network.add_a2a_server(planner_server)
    automa_network.add_a2a_server(gbxml_server)

    await automa_network.run()
    print("✅ gbXML network started on port 10001...")
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
    await automa_network.shutdown_all()
    print("🧹 MCP and A2A Servers stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
