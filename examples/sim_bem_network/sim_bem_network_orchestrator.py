from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.agents.remote_agent import SubAgentSpec
from automa_ai.common.agent_registry import A2AAgentServer, A2AServerManager
from automa_ai.common.mcp_registry import MCPServerConfig, MCPServerManager
from app_mcps import model_mcp, os_mcp

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
BLACKBOARD_BASE_DIR = BASE_DIR / ".demo_blackboards"
load_dotenv(dotenv_path=ENV_PATH)


COORDINATOR_COT = """
You are the BEM coordinator for an OpenStudio energy modeling workflow.

Use the shared blackboard as the source of truth.

Rules:
- Always call blackboard_read before deciding the next step.
- Ask for missing required information instead of guessing.
- Use the planner agent first when there is no task plan in the blackboard.
- If no model exists yet, use the model generator agent before any modification or simulation work.
- Use the envelope agent only for envelope requests such as window-to-wall-ratio updates.
- Use the lighting agent only for daylighting or lighting updates.
- Run simulations before asking the output agent for EUI results.
- When comparing savings, make sure both the original model and the modified model are simulated and evaluated.
- After each delegated task, read the blackboard again and decide the next step.

When you delegate, include the relevant blackboard state in the task text so the subagent has enough context.

Your final answer should summarize:
- what work was completed,
- which model paths were produced,
- which simulations were run,
- the EUI results or savings if available,
- any missing information still required from the user.
"""


PLANNER_COT = """
You are the planner for a building energy modeling team.

Use the blackboard as the source of truth.

Rules:
- Always call blackboard_read first.
- If the request is missing required information, ask one clear follow-up question.
- When you have enough information, write a concise task plan to the blackboard.
- Use only blackboard_write ops: set, merge, append, remove.
- Store the plan at path plan.
- Keep the plan short and actionable.

Typical task sequence:
1. Generate or load the original model.
2. Apply model modifications if requested.
3. Run simulation for the original model when comparison is needed.
4. Run simulation for the modified model when comparison is needed.
5. Retrieve EUI outputs.
6. Summarize the outcome.

Return a concise response that explains either:
- the missing input you still need, or
- the task plan that was written to the blackboard.
"""


TEMPLATE_COT = """
You generate an OpenStudio model template.

Use the blackboard as the source of truth.

Rules:
- Always call blackboard_read first.
- If blackboard already contains models.original_model_path, do not generate another model.
- If save_dir, building_type, energy_standard, or location are missing, ask one clear follow-up question.
- Use get_climate_by_location when location is available.
- Use load_openstudio_model once all required inputs are known.
- Write generated data back with blackboard_write.

Write these fields when successful:
- request.building_type
- request.energy_standard
- request.location
- models.original_model_path
- models.current_model_path
- models.climate_zone

Return a concise response describing what model was loaded or what input is missing.
"""


ENVELOPE_COT = """
You update the envelope of an OpenStudio model.

Use the blackboard as the source of truth.

Rules:
- Always call blackboard_read first.
- Use models.current_model_path if it exists, otherwise use models.original_model_path.
- If no model path exists, ask the coordinator to provide or generate a model first.
- Use modify_window_to_wall_ratio for window-to-wall-ratio changes.
- After a successful update, write:
  - models.modified_model_path
  - models.current_model_path
  - modifications.envelope

Return a concise response describing the envelope update or the missing prerequisite.
"""


LIGHTING_COT = """
You update lighting features in an OpenStudio model.

Use the blackboard as the source of truth.

Rules:
- Always call blackboard_read first.
- Use models.current_model_path if it exists, otherwise use models.original_model_path.
- If no model path exists, ask the coordinator to provide or generate a model first.
- Use add_daylight_sensor for daylighting requests.
- After a successful update, write:
  - models.modified_model_path
  - models.current_model_path
  - modifications.lighting

Return a concise response describing the lighting update or the missing prerequisite.
"""


SIMULATION_COT = """
You run OpenStudio simulations.

Use the blackboard as the source of truth.

Rules:
- Always call blackboard_read first.
- If the task mentions the original model, use models.original_model_path.
- If the task mentions the modified or updated model, use models.modified_model_path or models.current_model_path.
- Otherwise use models.current_model_path when available, else models.original_model_path.
- If the chosen model path is missing, ask for the prerequisite model.
- Use run_openstudio_simulation on the chosen model path.
- After a successful run, write a completion record under simulations.

Return a concise response describing which model was simulated.
"""


OUTPUT_COT = """
You retrieve simulation outputs from an OpenStudio model.

Use the blackboard as the source of truth.

Rules:
- Always call blackboard_read first.
- If the task mentions the original model, use models.original_model_path.
- If the task mentions the modified or updated model, use models.modified_model_path or models.current_model_path.
- Otherwise use models.current_model_path when available, else models.original_model_path.
- If the chosen model path is missing, ask for the prerequisite model.
- Use retrieve_openstudio_model_annual_site_eui on the chosen model path.
- Write the retrieved result under outputs.

Return a concise response describing the EUI result you retrieved.
"""


def load_card(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_blackboard_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "store": {
            "backend": "local_json",
            "base_dir": str(BLACKBOARD_BASE_DIR),
        },
        "schema_name": "sim_bem_workflow",
        "schema_version": "1.0.0",
        "schema_description": "Shared state for the sim_bem_network example.",
        "schema": {
            "type": "object",
            "properties": {
                "request": {"type": "object"},
                "plan": {"type": "object"},
                "models": {"type": "object"},
                "modifications": {"type": "object"},
                "simulations": {"type": "object"},
                "outputs": {"type": "object"},
            },
            "additionalProperties": True,
        },
        "initial_data": {
            "request": {},
            "plan": {"tasks": []},
            "models": {},
            "modifications": {},
            "simulations": {},
            "outputs": {},
        },
    }


def build_agent_factory(
    *,
    card: dict[str, Any],
    instructions: str,
    model_name: str,
    model_base_url: str | None = None,
    mcp_configs: dict[str, MCPServerConfig] | None = None,
    subagents: list[SubAgentSpec] | None = None,
    blackboard_config: dict[str, Any] | None = None,
) -> AgentFactory:
    return AgentFactory(
        card=card,
        instructions=instructions,
        model_name=model_name,
        model_base_url=model_base_url,
        agent_type=GenericAgentType.LANGGRAPHCHAT,
        chat_model=GenericLLM.OLLAMA,
        mcp_configs=mcp_configs,
        subagent_config=subagents,
        blackboard_config=blackboard_config,
        enable_metrics=True,
        debug=True,
    )


def build_server_configurations() -> tuple[MCPServerConfig, MCPServerConfig]:
    return (
        MCPServerConfig(
            name="oss_schema_mcp",
            host="localhost",
            port=10110,
            serve=os_mcp.serve,
            transport="sse",
        ),
        MCPServerConfig(
            name="oss_model_mcp",
            host="localhost",
            port=10118,
            serve=model_mcp.serve,
            transport="sse",
        ),
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    BLACKBOARD_BASE_DIR.mkdir(parents=True, exist_ok=True)

    planner_model_name = os.getenv("PLANNER_MODEL_NAME")
    planner_model_base_url = os.getenv("PLANNER_MODEL_BASE_URL") or None
    specialist_model_name = os.getenv("SPECIALIZED_AGENT_MODEL_NAME")

    oss_schema_mcp_config, oss_model_mcp_config = build_server_configurations()
    blackboard_config = build_blackboard_config()

    planner_card = load_card(BASE_DIR / "agent_cards" / "planner_agent.json")
    envelope_card = load_card(BASE_DIR / "agent_cards" / "envelope_agent.json")
    template_card = load_card(BASE_DIR / "agent_cards" / "template_agent.json")
    lighting_card = load_card(BASE_DIR / "agent_cards" / "lighting_agent.json")
    simulation_card = load_card(BASE_DIR / "agent_cards" / "simulation_agent.json")
    output_card = load_card(BASE_DIR / "agent_cards" / "output_agent.json")
    coordinator_card = load_card(
        BASE_DIR / "agent_cards" / "orchestrator_agent.json"
    )

    planner = build_agent_factory(
        card=planner_card,
        instructions=PLANNER_COT,
        model_name=planner_model_name,
        model_base_url=planner_model_base_url,
        blackboard_config=blackboard_config,
    )
    envelope_agent = build_agent_factory(
        card=envelope_card,
        instructions=ENVELOPE_COT,
        model_name=specialist_model_name,
        mcp_configs={"oss_schema_mcp": oss_schema_mcp_config},
        blackboard_config=blackboard_config,
    )
    template_agent = build_agent_factory(
        card=template_card,
        instructions=TEMPLATE_COT,
        model_name=specialist_model_name,
        mcp_configs={"oss_model_mcp": oss_model_mcp_config},
        blackboard_config=blackboard_config,
    )
    lighting_agent = build_agent_factory(
        card=lighting_card,
        instructions=LIGHTING_COT,
        model_name=specialist_model_name,
        mcp_configs={"oss_schema_mcp": oss_schema_mcp_config},
        blackboard_config=blackboard_config,
    )
    simulation_agent = build_agent_factory(
        card=simulation_card,
        instructions=SIMULATION_COT,
        model_name=specialist_model_name,
        mcp_configs={"oss_schema_mcp": oss_schema_mcp_config},
        blackboard_config=blackboard_config,
    )
    output_agent = build_agent_factory(
        card=output_card,
        instructions=OUTPUT_COT,
        model_name=specialist_model_name,
        mcp_configs={"oss_schema_mcp": oss_schema_mcp_config},
        blackboard_config=blackboard_config,
    )
    coordinator = build_agent_factory(
        card=coordinator_card,
        instructions=COORDINATOR_COT,
        model_name=planner_model_name,
        model_base_url=planner_model_base_url,
        subagents=[
            SubAgentSpec(
                name=planner_card["name"],
                description=planner_card["description"],
                agent_card=planner_card,
            ),
            SubAgentSpec(
                name=template_card["name"],
                description=template_card["description"],
                agent_card=template_card,
            ),
            SubAgentSpec(
                name=envelope_card["name"],
                description=envelope_card["description"],
                agent_card=envelope_card,
            ),
            SubAgentSpec(
                name=lighting_card["name"],
                description=lighting_card["description"],
                agent_card=lighting_card,
            ),
            SubAgentSpec(
                name=simulation_card["name"],
                description=simulation_card["description"],
                agent_card=simulation_card,
            ),
            SubAgentSpec(
                name=output_card["name"],
                description=output_card["description"],
                agent_card=output_card,
            ),
        ],
        blackboard_config=blackboard_config,
    )

    mcp_manager = MCPServerManager()
    mcp_manager.add_server(oss_schema_mcp_config)
    mcp_manager.add_server(oss_model_mcp_config)

    server_manager = A2AServerManager()
    server_manager.add_server(A2AAgentServer(coordinator, coordinator_card))
    server_manager.add_server(A2AAgentServer(planner, planner_card))
    server_manager.add_server(A2AAgentServer(envelope_agent, envelope_card))
    server_manager.add_server(A2AAgentServer(template_agent, template_card))
    server_manager.add_server(A2AAgentServer(lighting_agent, lighting_card))
    server_manager.add_server(A2AAgentServer(simulation_agent, simulation_card))
    server_manager.add_server(A2AAgentServer(output_agent, output_card))

    await mcp_manager.start_all()
    print("✅ MCP servers started.")
    await server_manager.start_all()
    print("✅ A2A Server started at http://localhost:10001/")
    print("Type 'exit' or 'stop' to shut down.")

    loop = asyncio.get_event_loop()
    while True:
        cmd = await loop.run_in_executor(None, input, "> ")
        if cmd.strip().lower() in {"exit", "stop", "quit"}:
            break

    print("🛑 Stopping servers...")
    await server_manager.stop_all()
    await mcp_manager.stop_all()
    print("🧹 MCP and A2A servers stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
