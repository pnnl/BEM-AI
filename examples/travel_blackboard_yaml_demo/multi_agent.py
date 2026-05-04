from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import httpx

from automa_ai.common.agent_registry import A2AServerManager
from automa_ai.config.agent_spec import YamlAgentSpec, load_a2a_server_from_yaml
from examples.travel_blackboard_yaml_demo.agents.common import (
    load_blackboard_config,
    register_travel_tools,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
SPECS_DIR = BASE_DIR / "specs"
SCHEMA_PATH = BASE_DIR / "blackboard_schema.json"
BLACKBOARD_BASE_DIR = BASE_DIR / ".demo_blackboards"
OLLAMA_BASE_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434")


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


def load_yaml_spec(path: Path, blackboard_config: dict) -> YamlAgentSpec:
    """Load one YAML agent spec and apply shared runtime paths for this demo."""
    spec = YamlAgentSpec.from_yaml_file(path)
    spec.model.base_url = OLLAMA_BASE_URL
    spec.blackboard = blackboard_config
    return spec


async def main() -> None:
    register_travel_tools()
    BLACKBOARD_BASE_DIR.mkdir(parents=True, exist_ok=True)
    blackboard_config = load_blackboard_config(
        SCHEMA_PATH,
        BLACKBOARD_BASE_DIR,
    ).model_dump()

    specs = [
        load_yaml_spec(SPECS_DIR / "orchestrator_agent.yaml", blackboard_config),
        load_yaml_spec(SPECS_DIR / "flight_agent.yaml", blackboard_config),
        load_yaml_spec(SPECS_DIR / "hotel_agent.yaml", blackboard_config),
        load_yaml_spec(SPECS_DIR / "car_agent.yaml", blackboard_config),
    ]

    server_manager = A2AServerManager()
    for spec in specs:
        server_manager.add_server(load_a2a_server_from_yaml(spec))

    print(ollama_health_message())
    print("▶ Starting YAML travel blackboard demo agents...")
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
