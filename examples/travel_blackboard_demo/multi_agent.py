from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import httpx
from a2a.types import AgentCard

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.agents.remote_agent import SubAgentSpec
from automa_ai.common.agent_registry import A2AAgentServer, A2AServerManager
from examples.travel_blackboard_demo.agents.common import load_blackboard_config, register_travel_tools

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
AGENTS_DIR = BASE_DIR / "agents"
SCHEMA_PATH = BASE_DIR / "blackboard_schema.json"
BLACKBOARD_BASE_DIR = BASE_DIR / ".demo_blackboards"
OLLAMA_BASE_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434")
MODEL_NAME = "llama3.1:8b"

register_travel_tools()

def load_card(path: Path) -> AgentCard:
    with path.open("r", encoding="utf-8") as f:
        return AgentCard(**json.load(f))


def ollama_health_message() -> str:
    try:
        response = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2.0)
        if response.status_code == 200:
            return f"✅ Ollama reachable at {OLLAMA_BASE_URL}."
        return (
            f"⚠️ Ollama at {OLLAMA_BASE_URL} responded with status {response.status_code}. "
            "Ensure the server is running and model llama3.1:8b is pulled."
        )
    except Exception:
        return (
            f"⚠️ Could not reach Ollama at {OLLAMA_BASE_URL}. "
            "Start Ollama and run: ollama pull llama3.1:8b."
        )


ORCHESTRATOR_INSTRUCTIONS = """
You are TravelOrchestratorAgent coordinating a blackboard-first travel booking workflow.

Blackboard policy addendum:
- Blackboard is source of truth.
- Always blackboard_read before taking action.
- Write updates only via blackboard_write.
- Allowed blackboard ops are strictly: set, merge, append, remove.
- Never use JSON Patch op names like replace/add/test.
- Paths are dot-style (example: requirements.origin or booking.status). Do not prefix with '/'.
- If requirements change (origin/destination/date/budget), mark quotes.*.stale=true, clear quotes.*.items, clear selection, and set booking.status='draft'.
- Ask user for any missing required fields before delegating.

Valid blackboard_write example:
blackboard_write(
  session_id="<current_session_id>",
  ops=[
    {"op": "set", "path": "requirements", "value": {...}},
    {"op": "set", "path": "booking.status", "value": "draft"}
  ]
)

Workflow:
1) Gather requirements (origin, destination, depart_date, return_date, budget, travelers).
2) Confirm requirements with the user.
3) Delegate quote generation to TravelFlightAgent, TravelHotelAgent, TravelCarAgent.
4) Present top 3 options from blackboard quotes.*.items.
5) Capture user selections (IDs or indices), write selection.* and booking.status='ready_to_book'.
6) On explicit user intent to book, delegate booking to subagents and present final itinerary with confirmations.
"""

FLIGHT_INSTRUCTIONS = """
You are TravelFlightAgent.
Use blackboard tools to read requirements and write outputs.
Use only blackboard ops: set, merge, append, remove.
Use dot-style paths only; never use '/requirements' or any leading slash path.
When user/orchestrator asks for quotes:
- blackboard_read requirements from shared board.
- if required fields missing, respond with missing fields.
- call tool travel_flight_provider with requirements.
- write items to path quotes.flights.items and set quotes.flights.stale=false.
When asked to book:
- blackboard_read selection.flight_id and session data.
- use the current session context id as blackboard session_id.
- call travel_booking_provider(category='flight', quote_id=selection.flight_id, session_id='<current_session_id>').
- write result under booking.confirmations.flight.
"""

HOTEL_INSTRUCTIONS = """
You are TravelHotelAgent.
Follow the same blackboard contract; use travel_hotel_provider for quotes and travel_booking_provider for booking.
Use only blackboard ops: set, merge, append, remove.
Use dot-style paths only; never use leading slash paths.
Write quote items to quotes.hotels.items and confirmation to booking.confirmations.hotel.
"""

CAR_INSTRUCTIONS = """
You are TravelCarAgent.
Follow the same blackboard contract; use travel_car_provider for quotes and travel_booking_provider for booking.
Use only blackboard ops: set, merge, append, remove.
Use dot-style paths only; never use leading slash paths.
Write quote items to quotes.cars.items and confirmation to booking.confirmations.car.
"""


def build_agent_factory(
    card: AgentCard,
    instructions: str,
    blackboard_config: dict,
    tools_config: dict | None = None,
    subagents: list[SubAgentSpec] | None = None,
) -> AgentFactory:
    return AgentFactory(
        card=card,
        instructions=instructions,
        model_name=MODEL_NAME,
        model_base_url=OLLAMA_BASE_URL,
        agent_type=GenericAgentType.LANGGRAPHCHAT,
        chat_model=GenericLLM.OLLAMA,
        tools_config=tools_config,
        subagent_config=subagents,
        blackboard_config=blackboard_config,
        enable_metrics=False,
        debug=False,
    )


async def main() -> None:
    BLACKBOARD_BASE_DIR.mkdir(parents=True, exist_ok=True)
    bb_cfg = load_blackboard_config(SCHEMA_PATH, BLACKBOARD_BASE_DIR).model_dump()

    orchestrator_card = load_card(AGENTS_DIR / "orchestrator_card.json")
    flight_card = load_card(AGENTS_DIR / "flight_card.json")
    hotel_card = load_card(AGENTS_DIR / "hotel_card.json")
    car_card = load_card(AGENTS_DIR / "car_card.json")

    flight_factory = build_agent_factory(
        card=flight_card,
        instructions=FLIGHT_INSTRUCTIONS,
        blackboard_config=bb_cfg,
        tools_config={"tools": [{"type": "travel_flight_provider"}, {"type": "travel_booking_provider"}]},
    )
    hotel_factory = build_agent_factory(
        card=hotel_card,
        instructions=HOTEL_INSTRUCTIONS,
        blackboard_config=bb_cfg,
        tools_config={"tools": [{"type": "travel_hotel_provider"}, {"type": "travel_booking_provider"}]},
    )
    car_factory = build_agent_factory(
        card=car_card,
        instructions=CAR_INSTRUCTIONS,
        blackboard_config=bb_cfg,
        tools_config={"tools": [{"type": "travel_car_provider"}, {"type": "travel_booking_provider"}]},
    )

    orchestrator_factory = build_agent_factory(
        card=orchestrator_card,
        instructions=ORCHESTRATOR_INSTRUCTIONS,
        blackboard_config=bb_cfg,
        subagents=[
            SubAgentSpec(name=flight_card.name, description=flight_card.description, agent_card=flight_card),
            SubAgentSpec(name=hotel_card.name, description=hotel_card.description, agent_card=hotel_card),
            SubAgentSpec(name=car_card.name, description=car_card.description, agent_card=car_card),
        ],
    )

    server_manager = A2AServerManager()
    server_manager.add_server(A2AAgentServer(orchestrator_factory, orchestrator_card))
    server_manager.add_server(A2AAgentServer(flight_factory, flight_card))
    server_manager.add_server(A2AAgentServer(hotel_factory, hotel_card))
    server_manager.add_server(A2AAgentServer(car_factory, car_card))

    print(ollama_health_message())
    print("▶ Starting travel blackboard demo agents...")
    await server_manager.start_all()
    print("✅ Orchestrator: http://localhost:33000/")
    print("✅ Flight agent: http://localhost:33001/")
    print("✅ Hotel agent: http://localhost:33002/")
    print("✅ Car agent: http://localhost:33003/")
    print("Type 'exit' or 'stop' to shut down.")

    loop = asyncio.get_event_loop()
    while True:
        cmd = await loop.run_in_executor(None, input, "> ")
        if cmd.strip().lower() in {"exit", "stop", "quit"}:
            break

    print("🛑 Stopping servers...")
    await server_manager.stop_all()


if __name__ == "__main__":
    asyncio.run(main())
