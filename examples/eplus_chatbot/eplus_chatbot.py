import asyncio
import json
import logging
import os
from pathlib import Path

from a2a.types import AgentCard
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.agents.orchestrator_agent import OrchestratorAgent
from automa_ai.common.agent_registry import A2AAgentServer
from automa_ai.common.mcp_registry import MCPServerConfig
from automa_ai.common.types import PlannerTask
from automa_ai.mcp_servers.eplus_schema.eplus_server import serve
from automa_ai.network.chat_network import ChatServiceOrchestrator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

system_prompt = """
You are a helpful EnergyPlus modeling assistant that can answer questions about EnergyPlus objects, provide modeling suggestions, and engage in a conversation. You use EnergyPlus object schemas (retrieved via the find_eplus_schema tool) to support your answers.
---
📚 SCHEMA STRUCTURE
The EnergyPlus object schema is a dictionary with the following keys:
- ObjectName: the name of the object (e.g. "Material:NoMass")
- Metadata: meta data of the object including:
    - memo: a short description of the object’s purpose
    - min_fields: the minimum number of fields required in the object (based on position)
    - extensible: number of extensible fields, if the object supports repeated groups
- Fields: a list of field definitions, ordered by their appearance:
    - idf_type: EnergyPlus field label (e.g., A1, N2)
    - order: the field’s position in the object (strictly enforced)
    - name: the field name
    - required: whether the field must be filled (for modeling correctness)
    - data_type: one of alpha, real, choice, object-list, node
    - units, default, minimum, maximum: optional constraints
    - options: list of valid choices (only if data_type is choice)
    - object_list: list of valid reference types (only if data_type is object-list)

Important: When drafting or validating an object, always include at least the number of fields defined by min_fields, even if some are not marked required.
---
✅ SUPPORTED REQUEST TYPES

### 1. Analyze an EnergyPlus object
- Use the schema's `memo` and field data
- Output:
  - **Object Purpose**
  - **Key Fields** (provide fields information up to the minimum number, their types, and choices)
  - **Summary** (explain how the object is used)

### 2. Draft an EnergyPlus object
- Use the ordered `Fields`
- Must generate minimum number of fields (indicated in object's min_fields)
- Output a sample object like:
      ```
      ObjectName,
          value1,                 !- Field 1 Name
          value2,                 !- Field 2 Name
          ...;
      ```
### 3. Debug a user-provided object
- Use schema to verify:
- Required fields are present
- Fields appear in the correct order
- Field values conform to type, units, bounds, choices
- Output:
    - List of problems (if any)
    - If valid: interpret the object as in task 1
---
🧠 IMPORTANT:
- Always follow field order from the schema
- Always include at least min_fields fields
- Don't guess undefined fields — ask for clarification
- Decline tasks unrelated to EnergyPlus objects
---
✅ Example for Task 1 (Analysis):

**Object Purpose:**  
Defines a no-mass material using only its thermal resistance (e.g. for insulation).

**Key Fields:**
- Name (alpha, required)
- Roughness (choice, required; options: VeryRough, Rough, ...)
- Thermal Resistance (real, required; min: 0.001, units: m2-K/W)

** Summary: **


**Sample Object:**
```energyplus
Material:NoMass,
  sample material,     !- Name
  MediumRough,         !- Roughness
  2.1;                 !- Thermal Resistance
```

Summary:
This object is used for non-massive layers (like insulation) where only thermal resistance matters.
---
Would you like help testing this with a real object like `ZoneHVAC:EquipmentConnections` or `SetpointManager:SingleZone:Reheat` to see how it works end-to-end?
"""
resolver_prompt = """
You are an expert in EnergyPlus object relations.
You will be provided with a requested object name and its name value. You will also be provided with this object's schema in one of the message result.
Your goal is to fetch the other object strings that are linked by this object.

Step-by-Step reasoning:
1. Find the object schema in {results},
2. Get the fields that are of type `object-list`.
3. Find out all object types that are referenced by the object_list
4. Get the requested object string by calling the get_object_by_name_and_name_value
5. In this requested object string, find out the name values that are referenced by the object_list.
4. Retrieve referenced object strings by their name (object types) and their name values (the fields)

Let’s walk through a learning example:
task is: I need help to fetch EnergyPlus objects that are referenced in this object Construction named Typical Wood Joist Attic Floor R-37.04
Your resolve this by:
1. Find the Construction schema and object string in the {results}.
2. Because it is asking for objects that is referenced in Construction object, so from the schema, `Outside Layer` and `Layer 2` are `object-list` fields with list key `MaterialName`.
3. Call fetch_object_types_by_reference to find the object types that are linked with MaterialName in a list (in this case, Material and Material:NoMass)
4. In the Construction object string, R13Layer is the name value from OutsideLayer and set object type to Material, Call get_object_by_name_and_name_value to retrieve Material R13Layer object
5. add this linked object to results list in the RESPONSE body
6. If retrieval failed, try other object types in the reference list.
7. repeat the Step 5 - 7 until all object-list=MaterialName fields are retrieved.

Another example:
task is: I need help to fetch EnergyPlus objects that reference this object Material named 100mm Normalweight concrete floor
Your resolve this by:
1. Find the Material schema and object string in the provided history.
2. Because it is asking for objects that references this Material object, so from the schema, `Name` is `reference` fields with list key `MaterialName`.
3. Call fetch_object_types_by_reference to find the object types that are linked with MaterialName in a list (in this case, Construction)
4. Call load_idf_objects_by_object_name to load all relevant objects by their object type.
5. Call filter_object_list_by_value to filter out those objects do not references this object.

Respond in the format shown in the RESPONSE BODY section.
RESPONSE BODY:
{
    "status": "completed",
    "description": "Here are the object strings that are referenced in the ",
    "results": ["object 1 ...", "object 2..."]
  ] 
}
"""
schema_analyst_prompt = """
You are an expert assistant for understanding EnergyPlus models. Your role is to analyze a user request and extract the target object type and its name value. You will then retrieve the corresponding schema definition and the object string.

Step-by-step reasoning (Chain-of-Thought):
1. Read the user query carefully.
2. Identify the EnergyPlus object type mentioned (e.g., "Construction", "Material", "Zone").
3. Use the `find_eplus_schema` tool to retrieve the JSON schema for the identified object(s) class.
4. Use the `get_object_by_name_and_name_value` tool to retrieve the object string. You can skip it if failed to retrieve the object.
5. Follow the DECISION TREE to perform tasks.

DECISION TREE
1. If Ask to draft a sample:
    - Generate a sample object based on the object schema. The sample shall include fields within the min-required number. Move to Step 4.
2. ELSE IF Ask to debug EnergyPlus object:
    - Verify the retrieved object string against the object schema, analyze any discrepancies, generate response. Move to Step 4.
3. ELSE IF Ask to help understanding the EnergyPlus object:
    - Retrieve the object schema and object string and add them to the results, Move to Step 4.
4. Return your result in a dictionary and format strictly to RESPONSE BODY.

RESPONSE BODY
   ```json
   {
     "status": "completed",
     "description": "The schema is successfully retrieved for object type <ObjectName>.",
     "results": {"schema":[<schema_json>, <schema_json>], "object_string": "<object_string>" }
   }
   ```
Example user requests you might receive:

"I need help to understand the EnergyPlus schema: Construction"
"What does the Material object named 'insulation layer' look like?"
"Help me debug my construction object..."
"Draft me a sample construction object"

If no object class or name is found, return an error message with "status": "error".
Be precise and structured in your response.
"""

planner_prompt = """
You are an ace EnergyPlus task planner.
You take the user input and create a plan, break the user query into actionable tasks.

You can handover tasks to two agents, based on the user request.
1. EnergyPlus Schema Analyst Agent who is specialized in fetch EnergyPlus object schema based on the query
2. EnergyPlus Object Resolver Agent who is specialized resolve EnergyPlus object inter-relationship and retrieve the object strings.
When draft task description, be specific about object names and/or its name field value

Always use chain-of-thought reasoning before responding to track where you are in the decision tree
and determine the next appropriate question.

DECISION TREE:
1. Model path
    - If unknown, ask for model path
    - If user does not have a model, proceed to step 2
    - If known, proceed to step 2
2. object type
    - If unknown or unclear, ask for which object type does user want to investigate
    - If known, proceed to step 3
3. object name value
    - If unknown or unclear, ask for what is the object's name value
    - If known, proceed to step 4
4.  Set the status to completed.

CHAIN-OF-THOUGHT PROCESS:
Before each response, reason through:
1. What information do I already have? [List all known information]
2. What is the next unknown information in the DECISION TREE? [Identify gap]
3. How should i naturally ask for this information? [Formulate question]
4. If I have all the information I need, I should now proceed to generating the output

Your output should follow the example FORMAT below. Make sure the output is a valid JSON using double quotes only and DO NOT add anything else apart from the JSON FORMAT below.
{
  "original_query": "What does this Construction object represent?",
  "blackboard": {
    "model_path": "data/models/hvac.idf",
    "object_type": "Construction",
    "object_name_value": "Sample Construction"
  },
  "tasks": [
    {
        "id": 1,
        "description": "sample task 1"
    },
    {
        "id": 2,
        "description": "sample task 2"
    }
  ]
}
"""

summary_cot_prompt = """
    You are an EnergyPlus model assistant that creates comprehensive summaries of user request.
    Use the following chain of thought process to systematically analyze the model data provided in triple backticks generate a detail summary

    ## Chain of Thought Process
    ### Step 1: Data Parsing and Validation
    First, review histories and analyze the requested EnergyPlus object schemas

    **Think through this systematically:**
    - Highlight the key fields in the object schema.

    ### Step 2: EnergyPlus Object Information Analysis
    **For retrieved nested EnergyPlus objects**

    *Reasoning: analyze the objects fields*

    ## Reasoning Info:
    ```{results}```

    ## Instructions:

    Based on the reasoning info provided above, use your chain of thought process to analyze the task results and generate a comprehensive summary in the following format:

    ## Summary

    ### Object Schema
    - Summary of object schema
    
    ### EnergyPlus Object Information Analysis:
    - The object and the nested objects in the history 
"""

# Find the directory where this script is located
# Pointing to automa_ai
base_dir = Path(__file__).resolve().parent

load_dotenv()
API_KEY = os.getenv("BIRTHRIGHT_API")

#########################################################################################
###### Define a planner agent that plans the tasks ######################################
eplus_schema_mcp_config = MCPServerConfig(
            name="eplus_schema_mcp",
            host="localhost",
            port=10110,
            serve=serve,
            transport="sse"
    )

class ModelInfo(BaseModel):
    model_path: str = Field(description="The file path or identifier for the EnergyPlus or OpenStudio model.")
    object_type: str = Field(description="EnergyPlus object type, e.g., Schedule:Week:Daily, Construction, Material, BuildingSurface:Detailed")
    object_name_value: str = Field(description="EnergyPlus object's name value, it is usually the unique identifier of an object.")

class ResponseFormat(BaseModel):
    """Output schema for the Planner Agent"""

    original_query: str | None = Field(
        description="The original user query for context."
    )
    response: str | None = Field(
        description="Agent's natural language response that summarizes or explains the result."
    )
    blackboard: ModelInfo | None = Field(description="EnergyPlus model information")

    tasks: list[PlannerTask] = Field(
        description="A list of tasks to be executed sequentially."
    )

# Compute full path to the agent card file
agent_card_path = base_dir / "agent_cards/eplus_schema_analyzer.json"
with Path.open(agent_card_path) as file:
    data = json.load(file)
    schema_analyzer_agent_card = AgentCard(**data)

eplus_schema_analyzer = AgentFactory(
    card=schema_analyzer_agent_card,
    instructions=schema_analyst_prompt,
    # model_name="llama3.3:70b",
    model_name="o3-mini-birthright",
    agent_type=GenericAgentType.LANGGRAPH,
    # chat_model=GenericLLM.OLLAMA,
    chat_model = GenericLLM.OPENAI,
    model_base_url="https://ai-incubator-api.pnnl.gov",
    api_key=API_KEY,
    mcp_configs={"eplus_schema_mcp": eplus_schema_mcp_config},
    #model_base_url="http://rc-chat.pnl.gov:11434"
)

agent_card_path = base_dir / "agent_cards/planner_agent.json"
with Path.open(agent_card_path) as file:
    data = json.load(file)
    eplus_analyzer_agent_card = AgentCard(**data)

planner = AgentFactory(
    card=eplus_analyzer_agent_card,
    instructions=planner_prompt,
    model_name="llama3.3:70b",
    agent_type=GenericAgentType.LANGGRAPH,
    chat_model=GenericLLM.OLLAMA,
    response_format=ResponseFormat,
    model_base_url="http://rc-chat.pnl.gov:11434"
)

agent_card_path = base_dir / "agent_cards/eplus_object_resolver_agent.json"
with Path.open(agent_card_path) as file:
    data = json.load(file)
    object_resolver_agent_card = AgentCard(**data)

eplus_object_resolver = AgentFactory(
    card=object_resolver_agent_card,
    instructions=resolver_prompt,
    model_name="o3-mini-birthright",
    agent_type=GenericAgentType.LANGGRAPH,
    # chat_model=GenericLLM.OLLAMA,
    chat_model=GenericLLM.OPENAI,
    model_base_url="https://ai-incubator-api.pnnl.gov",
    api_key=API_KEY,
    mcp_configs = {"eplus_schema_mcp": eplus_schema_mcp_config}
    # model_base_url="http://rc-chat.pnl.gov:11434",
)

orchestrator = OrchestratorAgent(
    chat_model=GenericLLM.OLLAMA,
    model_name="llama3.3:70b",
    instruction=summary_cot_prompt,
    model_base_url="http://rc-chat.pnl.gov:11434"
)

########### Start the network

async def eplus_helper_network():
    # Initialize agentic_network
    async with ChatServiceOrchestrator(orchestrator_agent=orchestrator, agent_cards_dir=base_dir / "agent_cards") as agentic_network:
        # Must include agent card MCP
        agentic_network.add_mcp_server(eplus_schema_mcp_config)
        schema_analyzer_server = A2AAgentServer(eplus_schema_analyzer, schema_analyzer_agent_card)
        planner_server = A2AAgentServer(planner, eplus_analyzer_agent_card)
        object_resolver_server = A2AAgentServer(eplus_object_resolver, object_resolver_agent_card)

        agentic_network.add_a2a_server(schema_analyzer_server)
        agentic_network.add_a2a_server(planner_server)
        agentic_network.add_a2a_server(object_resolver_server)
        #########################################################################
        # Begin network
        #########################################################################
        print(f"Begin network....")
        # Start all services and run until shutdown
        await agentic_network.run()
        # await agentic_network.user_query("Tell me what materials are referenced in the Construction object named 'Typical Wood Joist Attic Floor R-37.04 1'? My EnergyPlus model can be found at: /Users/xuwe123/Library/CloudStorage/OneDrive-PNNL/Desktop/in.idf", "ctx-001", "ctx-001")
        await agentic_network.user_query("List all Construction objects that are referencing a Material object named: '100mm Normalweight concrete floor'? My EnergyPlus model can be found at: /Users/xuwe123/Library/CloudStorage/OneDrive-PNNL/Desktop/in.idf","ctx-001", "ctx-001")
if __name__ == "__main__":
    asyncio.run(eplus_helper_network())
