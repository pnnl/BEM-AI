from __future__ import annotations

import asyncio
import inspect
import os
import sys
from pathlib import Path

import httpx

from automa_ai.config.agent_spec import YamlAgentSpec, load_agent_factory_from_yaml


BASE_DIR = Path(__file__).resolve().parent
COORDINATOR_SPEC = BASE_DIR / "coordinator.yaml"
OLLAMA_BASE_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_QUERY = (
    "Analyze data/monthly_results.csv. Compute annual electricity use, annual "
    "gas use, peak monthly demand, and flag any missing months. Return a short "
    "markdown summary."
)


def ollama_health_message() -> str:
    try:
        response = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2.0)
        if response.status_code == 200:
            return f"Ollama reachable at {OLLAMA_BASE_URL}."
        return (
            f"Ollama at {OLLAMA_BASE_URL} responded with status "
            f"{response.status_code}. Ensure the server is running and "
            "llama3.1:8b is pulled."
        )
    except Exception:
        return (
            f"Could not reach Ollama at {OLLAMA_BASE_URL}. "
            "Start Ollama and run: ollama pull llama3.1:8b."
        )


def load_coordinator():
    spec = YamlAgentSpec.from_yaml_file(COORDINATOR_SPEC)
    spec.model.base_url = OLLAMA_BASE_URL
    return load_agent_factory_from_yaml(spec).get_agent()


async def main() -> None:
    query = " ".join(sys.argv[1:]).strip() or DEFAULT_QUERY
    agent = load_coordinator()
    context_id = "headless-yaml-demo"
    task_id = "monthly-results-analysis"

    print(ollama_health_message())
    print(f"User query: {query}")
    print("\n--- Stream ---")

    try:
        async for item in agent.stream(query, context_id, task_id):
            content = item.get("content")
            if content:
                print(content, end="" if content.endswith("\n") else "\n")
    finally:
        close = getattr(agent, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result


if __name__ == "__main__":
    asyncio.run(main())
