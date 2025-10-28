################
# This is the same network as bem_network but
# using agent factory approach
################

import asyncio
import json
import logging
import os
from pathlib import Path

from a2a.types import AgentCard
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from typing import Literal

from automa_ai.agents import GenericLLM, GenericAgentType
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.agents.orchestrator_agent import OrchestratorAgent
from automa_ai.common.agent_registry import A2AAgentServer
from automa_ai.common.mcp_registry import MCPServerConfig
from automa_ai.mcp_servers.eplus_schema.eplus_server import serve
from automa_ai.network.task_workflow import TaskServiceOrchestrator
from automa_ai.common.types import TaskList

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Find the directory where this script is located
# Pointing to automa_ai
base_dir = Path(__file__).resolve().parent

load_dotenv()
API_KEY = os.getenv("BIRTHRIGHT_API")
###########################################################################################
##### Prompts #############################################################################

PLANNER_INSTRUCTION = """
You are the expert planner in building energy modeling using EnergyPlus, the workflow is draft objects, and have a reviewer to review the draft.

You have helpers that you need to delegate tasks to:
2. EnergyPlus object drafter: The EnergyPlus object drafter can generate objects based on user requests
3. EnergyPlus object reviewer: The EnergyPlus reviewers review the generated EnergyPlus objects and provide feedback to the planner.

CHAIN-OF-THOUGHT PROCESS:
Before each response, reason through:
1. What information do I already have? [List all known information]
2. What is the next unknown information in the DECISION TREE? [Identify gap]
3. How should i naturally ask for this information? [Formulate question]
4. If I have all the information I need, I should now proceed to generating the output follow the RESPONSE BODY format

Your output should follow this example format. Make sure the output is a valid JSON using double quotes only. 
DO NOT add anything else apart from the RESPONSE BODY in JSON format below.
{
    "original_query": "I need the geometry to be completed. The geometry is a simple box 20 meters long and 20 meters wide, and 5 meters high. It is a simple thermal zone. Use default constructions or standard materials. You can only generate the geometry and constructions and materials, No need HVAC system or lighting or other objects.",
    "blackboard":
    {
        "object_type": "Construction",
        "object_name_value": "Sample Construction",
    },
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

OBJECT_DRAFTER = """
You are an excellent EnergyPlus modeler and your job is to write EnergyPlus objects.

STEP-BY-STEP REASONING:
1. Call get_commonly_used_energyplus_objects tool to get a list of commonly used object types.
2. Understand the user query reasoning what object types are needed from the list.
3. Call find_multiple_energyplus_object_schema to retrieve object schemas for all selected object types
4. Develop object strings following the object schema strictly.
    - The object string MUST include number of fields that is equal or greater than min-fields or at minimum the first name field. 
    - The order of the field in the schema must be maintained in the object string.
    - Every energyplus object string starts with object type (e.g., Construction) and ends with ;
    - Object fields that has type `object-list` MUST be resolved to another object's reference. 
5. Once all object strings are generated, you should proceed to generate output in RESPONSE BODY format. All object strings shall be in a list 

Your output should follow this example format. Make sure the output is a valid JSON using double quotes only. 
{
    "status": "completed",
    "description": "Completed the generation of EnergyPlus objects",
    "results": [{drafted_object_string_1}, {drafted_object_string_2} ...]
}
"""

REVIEWER_DRAFTER  = """
You are a senior EnergyPlus modeler and you are tasked to review the drafter's work in the {history}.

CHAIN-OF-THOUGHT PROCESS:
Before each response, reason through:
1. In objects are drafted and does EnergyPlus has those object types? 
2. Obtain the object schemas based on object types
3. Review the schema requirements against the drafted object strings field by field to make sure every value is valid.
4. If the field is an object-list, make sure the linked object is also included in the draft.
5. If review shows issues, generate a task to planner to provide feedback and request to improve in the RESPONSE BODY, description field.
6. If review shows all correct, do not include tasks in the RESPONSE BODY.
Your output shall be strictly formatted to the RESPONSE BODY.

Example:

["Construction,
  Adiabatic floor construction,           !- Name
  CP02 CARPET PAD,                        !- Layer 1
  100mm Normalweight concrete floor,      !- Layer 2
  Nonres_Floor_Insulation;                !- Layer 3"
  ,
  "Material,
  100mm Normalweight concrete floor,      !- Name
  MediumSmooth,                           !- Roughness
  0.1016,                                 !- Thickness {m}
  2.31,                                   !- Conductivity {W/m-K}
  2322,                                   !- Density {kg/m3}
  832,                                    !- Specific Heat {J/kg-K}
  0.9,                                    !- Thermal Absorptance
  0.7,                                    !- Solar Absorptance
  0.7;                                    !- Visible Absorptance"
]

1. In the given list, two objects are drafted and their object types are Construction, Material.
2. Obtain Construction schema and Material schema, check schema requirements on each field, for example Conductivity in Material has minimum > 0, verify the value is greater than 0.
3. Notice that in the Construction, "Outside Layer", "Layer 1" etc fields are object-list, and the key is MaterialName.
4. Make sure those fields are properly referenced within the generated objects. In this case, Material object has the Name that matches to the Layer 2.
5. However, there is no Material object drafted that contains Layer 1 and Layer 3.


RESPONSE BODY:
{
    "status": "completed",
    "description": "Completed review with question",
    "results": [<object_1>, <object_2>, <object_3>...],
    "tasks": [
        {"id": 1, "description": "Revision plan: ..."}
    ]
}

"""

SUMMARY_INSTRUCTION = """
You are an EnergyPlus model assistant that creates comprehensive summaries of user request.
Use the following chain of thought process to systematically analyze the model data provided in triple backticks generate a detail summary

## Chain of Thought Process
### Step 1: Data Parsing and Validation
First, review histories and analyze the final approval results

**Think through this systematically:**
- Highlight the objects generated in this task

### Step 2: EnergyPlus Object Information Analysis
## Reasoning Info:
```{results}```

    ## Instructions:

    Based on the reasoning info provided above, use your chain of thought process to analyze the task results and generate a comprehensive summary in the following format:

    ## Summary

    ### Objects
    - List all objects generated in the task in an EnergyPlus format.

"""

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
    instructions=PLANNER_INSTRUCTION,
    # model_name="qwen3:14b",
    model_name="llama3.3:70b",
    agent_type=GenericAgentType.LANGGRAPH,
    chat_model=GenericLLM.OLLAMA,
    response_format=ResponseFormat,
    model_base_url="http://rc-chat.pnl.gov:11434"
)

#########################################################################################
##### Define Speciality agents ###############################################################
# MCP
eplus_schema_mcp_config = MCPServerConfig(
            name="eplus_schema_mcp",
            host="localhost",
            port=10110,
            serve=serve,
            transport="sse"
    )


obj_drafter_agent_card_path = base_dir / "agent_cards/drafter_agent.json"
with Path.open(obj_drafter_agent_card_path) as file:
    data = json.load(file)
    obj_drafter_agent_card = AgentCard(**data)

object_drafter = AgentFactory(
    card=obj_drafter_agent_card,
    instructions=OBJECT_DRAFTER,
    #model_name="qwen3:14b",
    model_name="o3-mini-birthright",
    agent_type=GenericAgentType.LANGGRAPH,
    # chat_model=GenericLLM.OLLAMA,
    # model_base_url="http://rc-chat.pnl.gov:11434",
    chat_model = GenericLLM.OPENAI,
    model_base_url="https://ai-incubator-api.pnnl.gov",
    api_key=API_KEY,
    mcp_configs={"eplus_schema_mcp": eplus_schema_mcp_config},
)

# Load model template agent.
reviewer_agent_card_path = base_dir / "agent_cards/reviewer_agent.json"
with Path.open(reviewer_agent_card_path) as file:
    data = json.load(file)
    reviewer_agent_card = AgentCard(**data)

reviewer = AgentFactory(
    card=reviewer_agent_card,
    instructions=REVIEWER_DRAFTER,
    model_name="o3-mini-birthright",
    # model_name="qwen3:14b",
    agent_type=GenericAgentType.LANGGRAPH,
    # chat_model=GenericLLM.OLLAMA,
    chat_model=GenericLLM.OPENAI,
    model_base_url="https://ai-incubator-api.pnnl.gov",
    api_key=API_KEY,
    mcp_configs={"eplus_schema_mcp": eplus_schema_mcp_config},
)

# Define your orchestrator agent that manages the workflow
orchestrator = OrchestratorAgent(
    chat_model=GenericLLM.OLLAMA,
    model_name="llama3.3:70b",
    instruction=SUMMARY_INSTRUCTION,
    model_base_url="http://rc-chat.pnl.gov:11434"
)

async def bem_agentic_network():
    # Initialize agentic_network
    async with TaskServiceOrchestrator(orchestrator=orchestrator, agent_cards_dir = base_dir / "agent_cards") as agentic_network:
        # Starts with MCP first
        agentic_network.add_mcp_server(eplus_schema_mcp_config)

        planner_server = A2AAgentServer(planner, agent_card)
        drafter_server = A2AAgentServer(object_drafter, obj_drafter_agent_card)
        reviewer_server = A2AAgentServer(reviewer, reviewer_agent_card)
        agentic_network.add_a2a_server(drafter_server)
        agentic_network.add_a2a_server(reviewer_server)
        agentic_network.add_a2a_server(planner_server)
        #########################################################################
        # Begin network
        #########################################################################
        print(f"Begin network....")
        # Start all services and run until shutdown
        await agentic_network.run()
        await agentic_network.user_query("Generate a simple building IDF file in EnergyPlus. I need the geometry to be completed. The geometry is a simple box 20 meters long and 20 meters wide, and 5 meters high. It is a simple thermal zone. Use default constructions or standard materials. You can only generate the geometry and constructions and materials, No need HVAC system or lighting or other objects.", "ctx-001", "ctx-001")


if __name__ == "__main__":
    asyncio.run(bem_agentic_network())
