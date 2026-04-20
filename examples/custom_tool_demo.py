from __future__ import annotations

import asyncio
import os
import math
from automa_ai.tools.decorators import tool

from a2a.types import AgentCard, AgentCapabilities

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.common.agent_registry import A2AAgentServer, A2AServerManager


@tool(name="compute_factorial")
def factorial(n: int) -> dict:
    """Compute the factorial of a non-negative integer n."""
    if n < 0:
        return {"error": "ValueError", "message": "n must be non-negative"}
    if n > 1000:
        return {"error": "ValueError", "message": "n too large (max 1000)"}
    return {"n": n, "result": str(math.factorial(n))}

ARITHMETIC_COT = """
You are a precise factorial calculator assistant. 
Do not attempt mental math, only use the factorial tool provided.
"""

AGENT_URL = "http://localhost:31000"
MODEL_NAME = "llama3.1:8b"
MODEL_BASE_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434")

tools_config = {
    "tools": [
        {"type": f"examples.custom_tool_demo.factorial"},
    ]
}

public_agent_card = AgentCard(
    name="Arithmetic Agent",
    description="An agent that performs exact arithmetic via calculator tools.",
    url=AGENT_URL,
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    supports_authenticated_extended_card=False,
    skills=[],
    capabilities=AgentCapabilities(streaming=True),
)


arithmetic_agent = AgentFactory(
    card=public_agent_card,
    instructions=ARITHMETIC_COT,
    model_name=MODEL_NAME,
    agent_type=GenericAgentType.LANGGRAPHCHAT,
    chat_model=GenericLLM.OLLAMA,
    model_base_url=MODEL_BASE_URL,
    tools_config=tools_config,
    enable_metrics=True,
    debug=True,

)

arithmetic_a2a = A2AAgentServer(arithmetic_agent, public_agent_card)

server_manager = A2AServerManager()
server_manager.add_server(arithmetic_a2a)


async def main():
    await server_manager.start_all()
    print(f"✅ Arithmetic Agent started at {AGENT_URL}")
    print("Type 'exit' or 'stop' to shut down.")

    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    async def wait_for_input():
        while True:
            cmd = await loop.run_in_executor(None, input, "> ")
            if cmd.strip().lower() in {"exit", "stop", "quit"}:
                stop_event.set()
                break

    await wait_for_input()
    print("🛑 Stopping server...")
    await server_manager.stop_all()
    print("🧹 Server stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(main())