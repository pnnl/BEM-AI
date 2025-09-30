import asyncio
import json
import logging
from pathlib import Path

from a2a.types import AgentCard
from google.adk.models.lite_llm import LiteLlm
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field
from typing import Literal

from agents.adk_agent import GenericADKAgent
from agents.react_langgraph_agent import GenericLangGraphReactAgent
from common import prompts
from common.agent_registry import A2AAgentServer
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


# Load Planner Agent Card
def planner_agent():
    return GenericLangGraphReactAgent(
        agent_name=agent_card.name,
        description=agent_card.description,
        instructions=prompts.PLANNER_COT_INSTRUCTIONS,
        response_format=ResponseFormat,
        chat_model=ChatOllama(model="llama3.1:8b", temperature=0),
    )


#########################################################################################
##### Define Speciality agents ###############################################################
# Load geometry agent.
# Compute full path to the agent card file
geo_agent_card_path = base_dir / "agent_cards/geometry_agent.json"
with Path.open(geo_agent_card_path) as file:
    data = json.load(file)
    geo_agent_card = AgentCard(**data)


def geo_modeler_agent():
    return GenericADKAgent(
        agent_name=geo_agent_card.name,
        description=geo_agent_card.description,
        instructions=prompts.GEOMETRY_COT_INSTRUCTIONS,
        chat_model=LiteLlm(model="ollama_chat/llama3.1:8b"),
    )


# Load model template agent.
tmp_agent_card_path = base_dir / "agent_cards/template_agent.json"
with Path.open(tmp_agent_card_path) as file:
    data = json.load(file)
    tmp_agent_card = AgentCard(**data)


def model_template_agent():
    return GenericADKAgent(
        agent_name=tmp_agent_card.name,
        description=tmp_agent_card.description,
        instructions=prompts.MODEL_TEMPLATE_COT_INSTRUCTIONS,
        chat_model=LiteLlm(model="ollama_chat/llama3.1:8b"),
    )


async def bem_agentic_network():
    # Initialize agentic_network
    async with TaskServiceOrchestrator(agent_cards_dir=base_dir / "agent_cards") as agentic_network:
        # Must include agent card MCP
        planner_server = A2AAgentServer(planner_agent, agent_card)
        geo_modeler_server = A2AAgentServer(geo_modeler_agent, geo_agent_card)
        model_template_server = A2AAgentServer(model_template_agent, tmp_agent_card)
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
