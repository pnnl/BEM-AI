import asyncio

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.agents.remote_agent import SubAgentSpec
from automa_ai.common.agent_registry import A2AServerManager, A2AAgentServer

#### MATH AGENT
math_skill = {
    "id": "basic_math",
    "name": "Basic Math",
    "description": "Performs simple arithmetic calculations",
    "tags": ["math", "calculation"],
    "examples": ["What is 3 * 7?", "Calculate 12 x 7"],
}

MATH_AGENT_URL = "http://localhost:31000"

math_agent_card = {
    "name": "Math Subagent",
    "description": "A subagent that performs basic arithmetic calculations.",
    "version": "1.0.0",
    "defaultInputModes": ["text"],
    "defaultOutputModes": ["text"],
    "capabilities": {"streaming": True},
    "supportedInterfaces": [
        {
            "url": MATH_AGENT_URL,
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        }
    ],
    "skills": [math_skill],
}

MATH_AGENT_COT = """
You are a math subagent.
Your job is to compute the result of arithmetic expressions.
Return only the final numeric answer.
"""

math_agent = AgentFactory(
    card=math_agent_card,
    instructions=MATH_AGENT_COT,
    agent_type=GenericAgentType.LANGGRAPHCHAT,
    chat_model=GenericLLM.OLLAMA,
    model_name="qwen3:4b",
    debug=True,
)

### COORDINATOR
coordinator_skill = {
    "id": "task_coordination",
    "name": "Task Coordination",
    "description": "Coordinates tasks and delegates calculations to subagents",
    "tags": ["coordination"],
    "examples": ["What is 12 * 7?"],
}

COORD_AGENT_URL = "http://localhost:30000"

coordinator_card = {
    "name": "Coordinator Agent",
    "description": "Main agent that delegates calculations to subagents.",
    "version": "1.0.0",
    "defaultInputModes": ["text"],
    "defaultOutputModes": ["text"],
    "capabilities": {"streaming": True},
    "supportedInterfaces": [
        {
            "url": COORD_AGENT_URL,
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        }
    ],
    "skills": [coordinator_skill],
}

COORDINATOR_COT = """
You are a coordinator agent.

## AGENT DELEGATION
- Math Subagent: Performs arithmetic calculations

Delegate calculation tasks to the Math Subagent when needed.
"""

coordinator_agent = AgentFactory(
    card=coordinator_card,
    instructions=COORDINATOR_COT,
    agent_type=GenericAgentType.LANGGRAPHCHAT,
    chat_model=GenericLLM.OLLAMA,
    model_name="qwen3:4b",
    subagent_config=[
        SubAgentSpec(
            name=math_agent_card["name"],
            description=math_agent_card["description"],
            agent_card=math_agent_card,
        )
    ],
    debug=True,
)


###### Add servers

math_a2a = A2AAgentServer(math_agent, math_agent_card)
coordinator_a2a = A2AAgentServer(coordinator_agent, coordinator_card)

server_manager = A2AServerManager()
server_manager.add_server(math_a2a)
server_manager.add_server(coordinator_a2a)


async def main():
    await server_manager.start_all()
    print("✅ A2A Server started at http://localhost:30000/")
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
