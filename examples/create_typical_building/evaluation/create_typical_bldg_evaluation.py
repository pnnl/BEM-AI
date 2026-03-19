import asyncio
import json
from pathlib import Path
import re
import sys
import traceback
import uuid
import os

# Add parent directory to path to import mcp_server
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from automa_ai.agents.langgraph_chatagent import GenericLangGraphChatAgent
from automa_ai.common.mcp_registry import MCPServerConfig, MCPServerManager
from automa_ai.common.utils import map_mcp_config_to_server_config
from deepeval.evaluate import evaluate
from deepeval.metrics import AnswerRelevancyMetric, ToolCorrectnessMetric, GEval
from deepeval.models import AzureOpenAIModel, AnthropicModel, OllamaModel, GPTModel
from deepeval.test_case import LLMTestCase, ToolCall, LLMTestCaseParams
from dotenv import load_dotenv
from langchain_core.messages import AIMessage
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from mcp_server.src.server import serve

base_dir = Path(__file__).resolve().parent
env_path = base_dir.parent / ".env"
load_dotenv(dotenv_path=env_path)

# Agent model configuration (Claude/BIRTHRIGHT)
chat_bot_model_name = os.environ.get("CHAT_BOT_MODEL_NAME")
chat_bot_base_url = os.environ.get("CHAT_BOT_MODEL_BASE_URL")
chat_bot_api_key = os.environ.get("BIRTHRIGHT_API") or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")

# Judge model configuration (for evaluation)
judge_model_name = os.environ.get("OLLAMA_MODEL_NAME")
judge_model_base_url = os.environ.get("OLLAMA_MODEL_BASE_URL")

create_typical_bldg_mcp_config = MCPServerConfig(
    name="create_typical_bldg_mcp",
    host="localhost",
    port=8082,
    serve=serve,
    transport="sse"
)

# Agent Instructions
FOUNDATIONAL_GEOMETRY_COT = """
You are a foundational geometry and building envelope specialist. Your role is to create the scaffolding for 
energy models by generating building geometries and applying appropriate construction sets based on ASHRAE standards.

## YOUR CAPABILITIES
1. **Geometry Generation**: Generate default building geometries based on ASHRAE building types (Office, Hospital, 
   School, Hotel, Retail, etc.)
2. **Construction Set Application**: Apply ASHRAE 90.1 construction sets based on:
   - Climate zone (e.g., 2A, 3C, 4A, 7)
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
- When defaulting to 90.1-2013 standard, explicitly inform the user
- Use get_available_building_types to verify building types when uncertain
- Use get_ashrae_enumeration_values to verify climate zone formats
- The resulting OpenStudio Model (.osm file) will serve as the foundation for adding HVAC, lighting, 
  service hot water, and other building systems in future steps

## AVAILABLE BUILDING TYPES
Use get_available_building_types tool to retrieve the current list of available building types.

## CLIMATE ZONES
Common zones: 1A, 2A, 2B, 3A, 3B, 3C, 4A, 4B, 4C, 5A, 5B, 5C, 6A, 6B, 7A, 7B, 8A
Use get_ashrae_enumeration_values to verify available climate zones.
"""


def extract_tool_list(block: str):
    """
    Convert a block like:
        [
            ToolCall(
                name="query_projects_by_description"
            )
        ]
    into:
        ["query_projects_by_description"]
    """
    names = re.findall(r'name\s*=\s*"([^"]+)"', block)
    return names


def parse_verbose_log(verbose_log: str):
    result = {}
    # ---------- Relevancy ----------
    statement_match = re.search(r"Statements:\s*\[(.*?)\]", verbose_log, re.DOTALL)
    if statement_match:
        raw = statement_match.group(1).strip()
        try:
            result["Statements"] = json.loads(f"[{raw}]")
        except:
            result["Statements"] = []

    # ---------- Truths ----------
    truths_match = re.search(
        r"Truths \(limit=None\):\s*(.*?)\n\s*Claims:", verbose_log, re.DOTALL
    )
    if truths_match:
        raw = truths_match.group(1).strip()
        try:
            result["Truths"] = json.loads(f"[{raw}]")
        except:
            result["Truths"] = []

    # ---------- Claims ----------
    claims_match = re.search(r"Claims:\s*(.*?)\n\s*Verdicts:", verbose_log, re.DOTALL)
    if claims_match:
        raw = claims_match.group(1).strip()
        try:
            result["Claims"] = json.loads(f"[{raw}]")
        except:
            result["Claims"] = []

    # ---------- Verdicts ----------
    verdicts_match = re.search(r"Verdicts:\s*(\[[\s\S]*?\])", verbose_log, re.DOTALL)
    if verdicts_match:
        raw = verdicts_match.group(1).strip()
        try:
            result["Verdicts"] = json.loads(raw)
        except:
            result["Verdicts"] = []

    # ----------------------------------------------------
    #                TOOL CORRECTNESS BLOCK
    # ----------------------------------------------------

    # --- Expected Tools ---
    expected_match = re.search(
        r"Expected Tools:\s*(\[[\s\S]*?\])", verbose_log, re.DOTALL
    )
    if expected_match:
        result["Expected Tools"] = extract_tool_list(expected_match.group(1))
    else:
        result["Expected Tools"] = []

    # --- Tools Called ---
    called_match = re.search(r"Tools Called:\s*(\[[\s\S]*?\])", verbose_log, re.DOTALL)
    if called_match:
        result["Tools Called"] = extract_tool_list(called_match.group(1))
    else:
        result["Tools Called"] = []

    # --- Available Tools ---
    available_match = re.search(r"Available Tools:\s*(\[[^\]]*\])", verbose_log)
    if available_match:
        result["Available Tools"] = extract_tool_list(available_match.group(1))
    else:
        result["Available Tools"] = []

    # --- Tool Selection Score ---
    score_match = re.search(r"Tool Selection Score:\s*([0-9.]+)", verbose_log)
    if score_match:
        result["Tool Selection Score"] = float(score_match.group(1))

    # --- Tool Selection Reason ---
    reason_match = re.search(r"Tool Selection Reason:\s*(.*)", verbose_log)
    if reason_match:
        result["Tool Selection Reason"] = reason_match.group(1).strip()

    return result


def load_json(file_path):
    try:
        with open(file_path, "r") as json_file:
            data = json.load(json_file)
        return data
    except FileNotFoundError:
        print(f"Error: The file at {file_path} was not found.")
        return None
    except json.JSONDecodeError:
        print(f"Error: The file at {file_path} is not a valid JSON file.")
        return None


async def main():

    # Initialize MCP server manager
    mcp_manager = MCPServerManager()
    mcp_manager.add_server(create_typical_bldg_mcp_config)
    await mcp_manager.start_all()
    print(
        f"✅ MCP Server started at http://{create_typical_bldg_mcp_config.host}:{create_typical_bldg_mcp_config.port}/"
    )

    # Create agent
    # Determine which chat model to use based on model name
    model_lower = chat_bot_model_name.lower()
    if 'claude' in model_lower:
        chat_model = ChatAnthropic(
            model=chat_bot_model_name,
            api_key=chat_bot_api_key,
            base_url=chat_bot_base_url,
            temperature=0,
            timeout=None,
            max_retries=2,
        )
    else:
        # Default to OpenAI-compatible for other models (including BIRTHRIGHT models)
        chat_model = ChatOpenAI(
            model=chat_bot_model_name,
            api_key=chat_bot_api_key,
            base_url=chat_bot_base_url,
            temperature=0,
            timeout=None,
            max_retries=2,
        )


    print("Agent model:", chat_bot_model_name)
    print("Agent API key starting with:", chat_bot_api_key[:10] if chat_bot_api_key else "None")
    print("Agent Base URL:", chat_bot_base_url)
    print()
    geometry_agent = GenericLangGraphChatAgent(
        agent_name="Building Geometry Generator",
        description="A helpful assistant with expertise in building energy modeling, geometry generation, and ASHRAE standards.",
        instructions=FOUNDATIONAL_GEOMETRY_COT,
        chat_model=chat_model,
        response_format=None,
        mcp_servers={
            "create_typical_bldg_mcp": map_mcp_config_to_server_config(create_typical_bldg_mcp_config)
        },
    )

    # LLM as a judge model
    print("Judge model:", judge_model_name)
    print("Judge base URL:", judge_model_base_url)
    judge_model = OllamaModel(
                model=judge_model_name,
                base_url=judge_model_base_url,
                temperature=0.7,
            )

    # llm_judge = os.environ.get("OPEN_AI_MODEL_NAME")
    # judge_model = GPTModel(
    #     model=llm_judge,
    #     _openai_api_key=os.environ.get("OPENAI_API_KEY"),
    #     temperature=0,
    # )
    # print("Judge model: ", llm_judge)
    # print("Judge base URL:", chat_bot_base_url)

    results = []

    metrics = [
        ToolCorrectnessMetric(
            model=judge_model,
            threshold=0.6,
            verbose_mode=True,
            available_tools=[
                ToolCall(name="generate_default_ashrae_geometry_osm"),
                ToolCall(name="get_default_geometry_osm"),
                ToolCall(name="get_available_building_types"),
                ToolCall(name="get_available_geometry_files"),
                ToolCall(name="get_ashrae_enumeration_values"),
                ToolCall(name="set_default_construction_set"),
                ToolCall(name="generate_example_with_default_construction_set"),
            ],
            include_reason=True,
        ),
        GEval(
            name="Correctness",
            criteria="Determine whether the actual output correctly handles building geometry generation requests, including proper tool selection, climate zone formatting, and clarification behavior.",
            evaluation_steps=[
                "Check if the actual output aligns with the expected output in terms of tool usage and response behavior.",
                "Verify that climate zones are formatted correctly (ASHRAE 169-2013-<zone>).",
                "Confirm that the agent asks for clarification when required information is missing.",
                "Consider partial correctness if some, but not all, behaviors are correctly demonstrated.",
            ],
            model=judge_model,
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
                LLMTestCaseParams.EXPECTED_OUTPUT,
            ],
        ),
    ]

    test_json_path = base_dir / "create_typical_bldg_test_data.json"
    # read in test data
    test_data = load_json(test_json_path)

    for test in test_data:
        question = test["query"]
        expected_output = test["expected_output"]
        expected_tools_called_str = test["correct_tools_call"]
        
        # Handle null case for expected tools
        if expected_tools_called_str is None:
            expected_tools_called = []
        else:
            expected_tools_called = expected_tools_called_str.split(", ")

        response = "No response"
        actual_tools_called = []
        
        actual_output = await geometry_agent.invoke(question, uuid.uuid4())
        if "messages" in actual_output:
            # Extract tool calls from all messages
            for msg in actual_output["messages"]:
                if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
                    for tool_call in msg.tool_calls:
                        # tool_call is typically a dict with 'name' key
                        tool_name = tool_call.get('name') if isinstance(tool_call, dict) else tool_call.name
                        if tool_name:
                            actual_tools_called.append(ToolCall(name=tool_name))
            
            # Extract final response text
            message = actual_output["messages"][-1]
            if isinstance(message, AIMessage):
                print("Printing the message: ..........", message.content)
                print(type(message.content))
                if isinstance(message.content, list):
                    content = message.content[-1]
                    if "type" in content and content["type"] == "text":
                        response = content["text"]
                    elif isinstance(content, str):
                        response = content
                else:
                    response = message.content

        test_case = LLMTestCase(
            input=question,
            actual_output=response,
            expected_output=expected_output,
            tools_called=actual_tools_called,
            expected_tools=[
                ToolCall(name=tool_name) for tool_name in expected_tools_called
            ],
        )

        try:
            print(f"--------------------->>>> {test_case}")
            res = evaluate(
                test_cases=[test_case],
                metrics=metrics,
            )
            test_result = res.test_results[0]
            eval_results = {
                "passed": test_result.success,
                "metrics_data": [
                    {
                        "metric": metric.name,
                        "passed": metric.success,
                        "score": metric.score,
                        "reason": metric.reason,
                        "verbose_logs": parse_verbose_log(metric.verbose_logs),
                    }
                    for metric in test_result.metrics_data
                ],
            }
        except Exception as exc:
            eval_results = {"error": str(exc)}
            traceback.print_exc()

        entry = {
            "question": question,
            "expected": expected_output,
            "actual_output": response,
            "deepeval_result": eval_results,
        }
        results.append(entry)
        print(f"question: {question[:80]!r} -> score summary: {entry}")

    output_path = base_dir / "create_typical_bldg_evaluation_output.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Saved results to {output_path}")

    await mcp_manager.stop_all()
    print("🧹 Server stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
