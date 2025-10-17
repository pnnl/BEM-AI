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
from common.agent_registry import A2AAgentServer
from common.mcp_registry import MCPServerConfig
from common.prompts import MODELER_SUMMARY_COT_INSTRUCTIONS
from examples.simple_bem_typical_building.app_mcps import model_mcp, os_mcp
from network.task_workflow import TaskServiceOrchestrator
from common.types import TaskList

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Find the directory where this script is located
# Pointing to src
base_dir = Path(__file__).resolve().parent

########################################################################################
######## Prompts #######################################################################
PLANNER_COT = """
You are the manager of an OpenStudio energy modeling team, you receive a user request and break it down into actionable tasks.

## Team
The agents in your team are:
1. Energy Model Generator Agent: Generates a typical energy model based on energy standard, building type and location.
2. Energy Model Envelope Agent: makes updates to building envelopes such as reducing window to wall ratio and surface (wall, roof, floor etc.) insulation adjustment.
3. Energy Model Lighting Agent: makes updates to lighting power densities, add or remove daylighting sensors.
4. Energy Simulation Agent: Perform an annual simulation to evaluate energy consumption of an OpenStudio model.
5. Energy Output Agent: Help to retrieve energy use intensity after a simulation

Always use chain-of-thought reasoning before generating tasks.
## QUESTION FORMAT
You question should follow the example format below:
{
    "status": "input_required",
    "question": {{add your question}}
}

CHAIN-OF-THOUGHT PROCESS:
Before each response, reason through:
1. What are my team's capabilities? [Understand your team's capability]
2. What information do I already have? [List all known information]
3. To leverage my team's capabilities, what is the next unknown information? [Identify gap]
4. How should i naturally ask for this information? [Formulate question]
5. If I have all the information I need, I should now proceed to generating tasks
Always include a task to run simulation on original model. Do not generate tasks for data analysis, or data comparisons.

## OUTPUT FORMAT
Your output should follow this example format. Make sure the output is a valid JSON using double quotes only. 
DO NOT add anything else apart from the JSON format below:
{
    "original_query": "I need a small office model",
    "blackboard":
    {
        "original_model_path": "/usr/model/abc.osm",
    },
    "status: "completed", "input-required", "error"
    "tasks": [
        {
            "id": 1,
            "description": "Sample task 1",
            "status": "pending"
        }, 
        {
            "id": 2,
            "description": "Sample task 2",
            "status": "pending"
        }
    ]
}
"""

ENVELOPE_COT = """
You are an energy modeler specialized in OpenStudio envelope updates.
Check out the blackboard to confirm if you have all the information needed to perform the task.
You do not need to check out the history. Instead, you should focus on your current task. 

Call appropriate tools to perform the task. If new data generated, add it to blackboard.
Your final output should strictly follow the example RESPONSE format:

RESPONSE:
{
    "status": "completed",
    "description": "Description of the task performed",
    "blackboard": {
        "original_model_path": {{the user provided or loaded energy model}},
        "updated_model_path": {{tool returned directory}}
        ...
    }
}
"""

TEMPLATE_COT = """
You only job is to verify user request and load an OpenStudio model representing a typical building.
Check blackboard. If blackboard has original_model_path, then generate RESPONSE 
DO NOT check the history. Instead, you should focus on your current task.

## QUESTION FORMAT
You question should follow the example format below:
{
    "status": "input_required",
    "question": {{add your question}}
}

Reasoning follow the DECISION TREE ONLY when blackboard does not have the original_model_path
DECISION TREE:
1. save_dir:
    - If unknown, ask user for a local directory to save the model
    - If known, move to step 2
2. building_type:
    - If unknown, ask user for the building type
    - If known, move to step 3
3. energy_standard:
    - If unknown, ask user for the energy standard (e.g., 90.1 2019)
    - If known, move to step 4
4. location:
    - If unknown, ask user for the location (e.g., Boulder, Colorado)
    - If known, move to step 5
5. generate the RESPONSE.

CHAIN-OF-THOUGHT PROCESS:
Before each response, reason through:
1. What information do I already have? [List all known information]
2. what is the next unknown information? [Identify gap]
3. How should i naturally ask for this information? [Formulate question]
4. If I have all the information I need, I should now proceed with the task

Call appropriate tools to perform the task. If new data generated, add it to blackboard.
Your final output should strictly follow the example RESPONSE format:

RESPONSE:
{
    "status": "completed",
    "description": "Loaded the model",
    "blackboard": {
        "original_model_path": {{save_dir}},
        {{some other new data}}
    }
}
"""

LIGHTING_COT = """
You are an energy modeler specialized in OpenStudio lighting updates.
Check out the blackboard to confirm if you have all the information needed to perform the task.
You do not need to check out the history. Instead, you should focus on your current task.

Call appropriate tools to perform the task. If new data generated, add it to blackboard.
Your final output should strictly follow the example RESPONSE format:

RESPONSE:
{
    "status": "completed",
    "description": "Description of the task performed",
    "blackboard": {
        "original_model_path": new_path
        "updated_model_path": {{tool returned directory}}
        {{new data}}
    }
}
"""

SIMULATION_COT = """
Your only job is to call a tool to run annual simulation.
You should NOT check the history, instead, focus on your primary task.

Based on the query request, you can select a model path in the blackboard.
If new data generated, add it to blackboard.

Your final output should strictly follow the example RESPONSE format:

RESPONSE:
{
    "status": "completed",
    "description": "Completed the simulation",
    "blackboard": {
        {{new data}}
    }
}

"""

OUTPUT_COT = """
Your only task is to retrieve simulation outputs from an OpenStudio model path.
You should NOT check the history, instead, focus on your only task.
Check out the blackboard to confirm if you have the model paths. OpenStudio simulation results can be retrieved from the model itself instead of its output folder.
If there are multiple model paths, iteratively retrieve the simulation outputs per model path.

Call appropriate tools to perform the task. If new data generated, add it to blackboard.
Your final output should strictly follow the example RESPONSE format:
RESPONSE:
{
    "status": "completed",
    "description": "Description of the task performed",
    "blackboard": {
        {{new data}}
    }
}
"""

SUMMARY_COT = """
Your job is to summarize the work that has performed.
Your summary shall follow the format below.

In each section, there is an instruction to follow when generating the summary.

### Task
{query}

### Building Energy Modeling Task
In this section, you need to analyze what task has been performed by reading the {results}

### Modeling Meta Data
In this section, provide a summary based on {blackboard}

### Summary
Based on the above information, summarize the work that has performed in this task.

"""

#########################################################################################
###### MCP ######################################
oss_schema_mcp_config = MCPServerConfig(
            name="oss_schema_mcp",
            host="localhost",
            port=10110,
            serve=os_mcp.serve,
            transport="sse"
    )

oss_model_mcp_config = MCPServerConfig(
    name="oss_model_mcp",
    host="localhost",
    port=10118,
    serve=model_mcp.serve,
    transport="sse"
)

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
    instructions=PLANNER_COT,
    model_name="llama3.3:70b",
    agent_type=GenericAgentType.LANGGRAPH,
    chat_model=GenericLLM.OLLAMA,
    response_format=ResponseFormat,
    model_base_url="http://rc-chat.pnl.gov:11434"
)

#########################################################################################
##### Define Speciality agents ###############################################################
# Load geometry agent.
# Compute full path to the agent card file
env_agent_card_path = base_dir / "agent_cards/envelope_agent.json"
with Path.open(env_agent_card_path) as file:
    data = json.load(file)
    env_agent_card = AgentCard(**data)

env_modeler = AgentFactory(
    card=env_agent_card,
    instructions=ENVELOPE_COT,
    model_name="qwen3:4b",
    agent_type=GenericAgentType.LANGGRAPH,
    chat_model=GenericLLM.OLLAMA,
    mcp_configs={"oss_schema_mcp": oss_schema_mcp_config}
)

# Load model template agent.
tmp_agent_card_path = base_dir / "agent_cards/template_agent.json"
with Path.open(tmp_agent_card_path) as file:
    data = json.load(file)
    tmp_agent_card = AgentCard(**data)

template_modeler = AgentFactory(
    card=tmp_agent_card,
    instructions=TEMPLATE_COT,
    model_name="qwen3:4b",
    agent_type=GenericAgentType.LANGGRAPH,
    chat_model=GenericLLM.OLLAMA,
    mcp_configs={"oss_model_mcp": oss_model_mcp_config}
)

# Load lighting model agent
ltg_agent_card_path = base_dir / "agent_cards/lighting_agent.json"
with Path.open(ltg_agent_card_path) as file:
    data = json.load(file)
    ltg_agent_card = AgentCard(**data)

lighting_modeler = AgentFactory(
    card=ltg_agent_card,
    instructions=LIGHTING_COT,
    model_name="qwen3:4b",
    agent_type=GenericAgentType.LANGGRAPH,
    chat_model=GenericLLM.OLLAMA,
    mcp_configs={"oss_schema_mcp": oss_schema_mcp_config}
)

# Load simulation model agent
sim_agent_card_path = base_dir / "agent_cards/simulation_agent.json"
with Path.open(sim_agent_card_path) as file:
    data = json.load(file)
    sim_agent_card = AgentCard(**data)

simulation_agent = AgentFactory(
    card=sim_agent_card,
    instructions=SIMULATION_COT,
    model_name="qwen3:4b",
    agent_type=GenericAgentType.LANGGRAPH,
    chat_model=GenericLLM.OLLAMA,
    mcp_configs={"oss_schema_mcp": oss_schema_mcp_config}
)

# EnergyPlus output agent
output_agent_card_path = base_dir / "agent_cards/output_agent.json"
with Path.open(output_agent_card_path) as file:
    data = json.load(file)
    output_agent_card = AgentCard(**data)

output_agent = AgentFactory(
    card=output_agent_card,
    instructions=OUTPUT_COT,
    model_name="qwen3:4b",
    agent_type=GenericAgentType.LANGGRAPH,
    chat_model=GenericLLM.OLLAMA,
    mcp_configs={"oss_schema_mcp": oss_schema_mcp_config}
)

# Define your orchestrator agent that manages the workflow
orchestrator = OrchestratorAgent(
    chat_model=GenericLLM.OLLAMA,
    model_name="llama3.3:70b",
    instruction=MODELER_SUMMARY_COT_INSTRUCTIONS,
    model_base_url="http://rc-chat.pnl.gov:11434"
)

async def bem_agentic_network(user_query:str):
    # Initialize agentic_network
    async with TaskServiceOrchestrator(orchestrator=orchestrator, agent_cards_dir = base_dir / "agent_cards") as agentic_network:
        # Starts with MCP first
        agentic_network.add_mcp_server(oss_schema_mcp_config)
        agentic_network.add_mcp_server(oss_model_mcp_config)

        planner_server = A2AAgentServer(planner, agent_card)
        env_modeler_server = A2AAgentServer(env_modeler, env_agent_card)
        lighting_server = A2AAgentServer(lighting_modeler, ltg_agent_card)
        model_template_server = A2AAgentServer(template_modeler, tmp_agent_card)
        sim_server = A2AAgentServer(simulation_agent, sim_agent_card)
        output_server = A2AAgentServer(output_agent, output_agent_card)

        agentic_network.add_a2a_server(model_template_server)
        agentic_network.add_a2a_server(env_modeler_server)
        agentic_network.add_a2a_server(planner_server)
        agentic_network.add_a2a_server(lighting_server)
        agentic_network.add_a2a_server(sim_server)
        agentic_network.add_a2a_server(output_server)
        #########################################################################
        # Begin network
        #########################################################################
        print(f"Begin network....")
        # Start all services and run until shutdown
        await agentic_network.run()
        # await agentic_network.user_query("Create an energy model for a new office.", "ctx-001", "ctx-001")
        # await agentic_network.user_query("I have a model in local directory: /Users/xuwe123/ai/os-std-mod-mcp-server/resources/baseline.osm, I want to update the model window to wall ratio to 0.35", "ctx-001", "ctx-001")
        # await agentic_network.user_query("I have a model in local directory: /Users/xuwe123/ai/os-std-mod-mcp-server/resources/baseline.osm, Use this model to evaluate the energy savings from reducing window to wall ratio by 10%", "ctx-001", "ctx-001")
        await agentic_network.user_query(user_query, "ctx-001", "ctx-001")
        # await agentic_network.user_query("I want to evaluate the energy savings from reducing window to wall ratio by 10% for a medium office building that is designed according to ASHRAE 90.1 2019 in Tampa Florida", "ctx-001", "ctx-001")
        # await agentic_network.user_query("I have a model in local directory: /Users/xuwe123/ai/experiment/baseline.osm, I want to evaluate the energy savings by adding daylighting sensors", "ctx-001", "ctx-001")
if __name__ == "__main__":
    title = """
    🛠️  🏢  🏗️  ╔════════════════════════╗
    🟢           B E M - A I           
    🛡️  ⚡  💡  ╚════════════════════════╝
    """
    print(title)
    user_query = input(
        "🛠️ Thank you for using BEM-AI! I am your assistant to help analyze building performance 🏢\n"
        "💡 You can ask questions such as:\n"
        "   • 🔹 What is the energy savings from reducing window-to-wall ratio by 10%?\n"
        "   • 🔹 Create an energy model for a new office.\n\n"
        "✍️ Your question: "
    )
    asyncio.run(bem_agentic_network(user_query))
