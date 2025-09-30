################
# This is the same network as bem_network but
# using agent factory approach
################

import asyncio
import json
import logging
from pathlib import Path

from a2a.types import AgentCard
from pydantic import BaseModel, Field
from typing import Literal

from agents import GenericLLM, GenericAgentType
from agents.agent_factory import AgentFactory
from agents.orchestrator_agent import OrchestratorAgent
from common import prompts
from common.agent_registry import A2AAgentServer
from common.prompts import MODELER_SUMMARY_COT_INSTRUCTIONS
from network.task_workflow import TaskServiceOrchestrator
from common.types import TaskList

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Find the directory where this script is located
# Pointing to src
base_dir = Path(__file__).resolve().parent


#########################################################################################
###### Define a planner agent that plans the tasks ######################################
class ResponseFormat(BaseModel):
    status: Literal["input_required", "completed", "error"] = "input_required"
    question: str = Field(description="Input needed from the user to generate the plan")
    content: TaskList = Field(description="List of tasks when the plan is generated")


# Compute full path to the agent card file
agent_card_path = base_dir / "agent_cards/planner_agent.json"
with Path.open(agent_card_path) as file:
    data = json.load(file)
    agent_card = AgentCard(**data)

planner = AgentFactory(
    card=agent_card,
    instructions=prompts.PLANNER_COT_INSTRUCTIONS,
    model_name="llama3.1:8b",
    agent_type=GenericAgentType.LANGGRAPH,
    chat_model=GenericLLM.OLLAMA,
    response_format=ResponseFormat,
)

#########################################################################################
##### Define Speciality agents ###############################################################
# Load geometry agent.
# Compute full path to the agent card file
geo_agent_card_path = base_dir / "agent_cards/geometry_agent.json"
with Path.open(geo_agent_card_path) as file:
    data = json.load(file)
    geo_agent_card = AgentCard(**data)

geo_modeler = AgentFactory(
    card=geo_agent_card,
    instructions=prompts.GEOMETRY_COT_INSTRUCTIONS,
    model_name="ollama_chat/llama3.1:8b",
    agent_type=GenericAgentType.ADK,
    chat_model=GenericLLM.LITELLAMA,
)

# Load model template agent.
tmp_agent_card_path = base_dir / "agent_cards/template_agent.json"
with Path.open(tmp_agent_card_path) as file:
    data = json.load(file)
    tmp_agent_card = AgentCard(**data)

template_modeler = AgentFactory(
    card=tmp_agent_card,
    instructions=prompts.MODEL_TEMPLATE_COT_INSTRUCTIONS,
    model_name="ollama_chat/llama3.1:8b",
    agent_type=GenericAgentType.ADK,
    chat_model=GenericLLM.LITELLAMA,
)

# Define your orchestrator agent that manages the workflow
orchestrator = OrchestratorAgent(
    chat_model=GenericLLM.OLLAMA,
    model_name="llama3.3:70b",
    instruction=MODELER_SUMMARY_COT_INSTRUCTIONS,
    model_base_url="http://rc-chat.pnl.gov:11434"
)

async def bem_agentic_network():
    # Initialize agentic_network
    async with TaskServiceOrchestrator(orchestrator=orchestrator, agent_cards_dir = base_dir / "agent_cards") as agentic_network:
        # Must include agent card MCP
        planner_server = A2AAgentServer(planner, agent_card)
        geo_modeler_server = A2AAgentServer(geo_modeler, geo_agent_card)
        model_template_server = A2AAgentServer(template_modeler, tmp_agent_card)
        agentic_network.add_a2a_server(model_template_server)
        agentic_network.add_a2a_server(geo_modeler_server)
        agentic_network.add_a2a_server(planner_server)
        #########################################################################
        # Begin network
        #########################################################################
        print(f"Begin network....")
        # Start all services and run until shutdown
        await agentic_network.run()
        await agentic_network.user_query("Create an energy model for a new office.", "ctx-001", "ctx-001")


if __name__ == "__main__":
    asyncio.run(bem_agentic_network())
